import logging.handlers
import socket
import threading
import struct
import time
import datetime
import logging
import os

monitor_lidar_data_clients = []  # Lidarデータ監視用のクライアントのリスト
monitor_time_delay_clients = []  # 通信遅延監視用のクライアントのリスト


# 🔹 **INFO 以下のログのみを `info.log` に記録するフィルタ**
class Info_Filter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING  # INFO以下を許可


def logging_setup():
    
    global logger
    
    info_log_dir = "/app/logs/info_logs"
    error_log_dir = "/app/logs/error_logs"
    
    os.makedirs(info_log_dir, exist_ok=True)
    os.makedirs(error_log_dir, exist_ok=True)
    
    # ロガー作成
    logger = logging.getLogger("MyLogger")
    logger.setLevel(logging.DEBUG)  # すべてのログを処理対象にする

    # 📂 **Liderデータ（DEBUGのみ）を `lider_data.log` に保存**
    info_handler = logging.handlers.RotatingFileHandler(
        os.path.join(info_log_dir, "info.log"),
        encoding="utf-8",
        maxBytes=1024*1024*10,
        backupCount=5
    )
    info_handler.setLevel(logging.DEBUG)  # DEBUG 以上を記録（後でフィルタで制御）
    # 📂 **エラーログ（ERROR 以上）を `error.log` に保存**
    error_handler = logging.handlers.RotatingFileHandler(
        os.path.join(error_log_dir, "error.log"),
        encoding="utf-8",
        maxBytes=1024*1024*10,
        backupCount=5
    )
    error_handler.setLevel(logging.WARNING)  # WARNING 以上のみ記録
    #console_handler = logging.StreamHandler()
    #console_handler.setLevel(logging.DEBUG)

    # 🔹 **フォーマット設定**
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    info_handler.setFormatter(formatter)
    error_handler.setFormatter(formatter)
    #console_handler.setFormatter(formatter)

    # フィルタを適用
    info_handler.addFilter(Info_Filter())

    # 🔹 **ロガーにハンドラーを追加**
    logger.addHandler(info_handler)
    logger.addHandler(error_handler)
    #logger.addHandler(console_handler)  # コンソール出力
    logger.info("Logger setuped")


def format_timestamp(timestamp_us):
    """
    クライアントから受信したマイクロ秒単位のUNIXタイムスタンプを
    'HH:MM:SS.sss 遅延: X.XXX秒' の形式に変換する
    """
    timestamp_s = timestamp_us / 1e6  # マイクロ秒を秒単位に変換
    utc_time = datetime.datetime.utcfromtimestamp(timestamp_s)  # UTC時間に変換
    japan_time = utc_time + datetime.timedelta(hours=9)  # 日本時間(JST)に変換

    now_us = int(time.time() * 1e6)  # 現在のタイムスタンプ（マイクロ秒単位）
    delay_s = (now_us - timestamp_us) / 1e6  # 遅延（秒）

    # 遅延が負の値になるのを防ぐ（通常は発生しないはず）
    delay_s = max(0, delay_s)

    formatted_time = japan_time.strftime("%H:%M:%S.%f")[:-3]  # 'HH:MM:SS.sss'（ミリ秒単位まで）
    return f"Time: {formatted_time} Delay: {delay_s:.3f}sec"

def decompress_data(data):
    """
    Decompress binary data into human-readable format.
    """
    decompressed = []
    buffer = memoryview(data)
    current_theta = None
    current_dist = None
    bit_buffer = 0
    bit_count = 0
    data_index = 0

    # 🔹 最後の64ビット（8バイト）をタイムスタンプとして取り出す
    if len(buffer) < 8:
        raise ValueError("Not enough data for timestamp")
    
    timestamp = struct.unpack(">Q", buffer[-8:])[0]  # 64ビット整数を取得
    buffer = buffer[:-8]  # タイムスタンプ部分を除いたデータ


    def read_bits(num_bits):
        """
        Helper function to read `num_bits` bits from `bit_buffer`.
        """
        nonlocal bit_buffer, bit_count, data_index, buffer
        while bit_count < num_bits:
            if data_index < len(buffer):
                bit_buffer = (bit_buffer << 8) | buffer[data_index]
                data_index += 1
                bit_count += 8
            else:
                raise ValueError("Not enough data to read")
        value = (bit_buffer >> (bit_count - num_bits)) & ((1 << num_bits) - 1)
        bit_count -= num_bits

        # 符号付き整数の補正
        if value & (1 << (num_bits - 1)):
            value -= (1 << num_bits)

        return value

    while data_index < len(buffer) or bit_count >= 11:
        if current_theta is None:
            # 初期値（11ビット角度 + 16ビット距離）
            theta = read_bits(11)
            dist = read_bits(16)
            current_theta = theta / 100.0
            current_dist = dist
        else:
            # 差分適用（11ビット角度差分 + 16ビット距離差分）
            theta_diff = read_bits(11)
            dist_diff = read_bits(16)
            current_theta += theta_diff / 100.0
            current_dist += dist_diff

        decompressed.append((current_theta, current_dist))

    return timestamp, decompressed

def filter_invalid_data(decompressed_data):
    """
    サーバー側でデータをフィルタリングして、異常な値を排除する
    """
    filtered_data = []
    delete_data_count = 0
    prev_theta = None

    for theta, dist in decompressed_data:
        # 角度の範囲チェック（0°～360°）
        if not (0.0 <= theta <= 360.0):
            logger.warning(f"Warning: Invalid theta value detected: {theta:.2f}, skipping...")
            delete_data_count += 1
            continue

        # 距離の範囲チェック（0mm～10m = 0mm～10000mm）
        if not (0 <= dist <= 14000):
            logger.warning(f"Warning: Invalid distance value detected: {dist}, skipping...")
            delete_data_count += 1
            continue

        # 角度の連続性チェック（急激なジャンプを排除）
        if prev_theta is not None and abs(theta - prev_theta) > 100.0:
            logger.warning(f"Warning: Sudden jump detected in theta values ({prev_theta:.2f} → {theta:.2f}), skipping...")
            delete_data_count += 1
            continue

        filtered_data.append((theta, dist))
        prev_theta = theta

    return filtered_data, delete_data_count

def handle_lidar_client(client_socket):
    """
    Handle incoming data from a LiDAR client.
    """
    try:
        buffer = bytearray()
        while True:
            data = client_socket.recv(8192)
            if not data:
                break
            buffer.extend(data)

            send_message = str()

            try:
                timestamp, decompressed_data = decompress_data(buffer)
                total_data_count = len(decompressed_data)
                send_message = f"\nReceived data count: {total_data_count}"

                # 🔹 追加: サーバー側で異常値をフィルタリング
                filtered_data, delete_data_count = filter_invalid_data(decompressed_data)

                # データ数チェック
                if len(filtered_data) < 300 or len(filtered_data) > 700:
                    logger.warning(f"Warning: Skipping this rotation due to invalid data count: {len(filtered_data)}")
                    timestamp_info = "\n" + format_timestamp(timestamp)
                    delete_data_info = f"\nDelete data count: {total_data_count}"
                    send_message += f"{delete_data_info}{timestamp_info}\n"
                    for monitor_socket in monitor_time_delay_clients[:]:
                        try:
                            monitor_socket.sendall(send_message.encode("utf-8"))
                        except Exception as e:
                            logger.exception(f"send monitor time delay client is faild {e}")
                    buffer = bytearray()  # バッファをリセット
                    continue

                # 🔹 タイムスタンプと遅延を追加して表示
                human_readable = "\n".join([f"Theta: {theta:.2f}, Distance: {dist}" for theta, dist in filtered_data]) + "\n"
                timestamp_info = "\n" + format_timestamp(timestamp)
                delete_data_info = f"\nDelete data count: {delete_data_count}"
                send_message += f"{delete_data_info}{timestamp_info}\n"
                formatted_output = f"{human_readable}{timestamp_info}"
                logger.debug(formatted_output)
                print(formatted_output, end="")  # 余計な改行を防ぐ

                # 監視用クライアントに送信
                for monitor_socket in monitor_lidar_data_clients[:]:
                    try:
                        monitor_socket.sendall(human_readable.encode("utf-8"))
                    except Exception as e:
                        logger.exception(f"send monitor Lidar data client is faild {e}")
                 
                for monitor_socket in monitor_time_delay_clients[:]:
                    try:
                        monitor_socket.sendall(send_message.encode("utf-8"))
                    except Exception as e:
                        logger.exception(f"send monitor time delay client is faild {e}")


                buffer = bytearray()  # Reset buffer after processing
            except ValueError as e:
                logger.exception(e)
    
    except Exception as e:
        logger.exception(e)
    
    finally:
        client_socket.close()
        logger.warning("LiDAR Client disconnected")

def handle_monitor_client(monitor_socket, address, monitor_clients):
    """
    Handle a client connected to the monitoring port (8001).
    """
    logger.info(f"Monitoring client connected: {address}")
    monitor_clients.append(monitor_socket)
    try:
        while True:
            data = monitor_socket.recv(1024)  # Keep connection open for streaming
            if not data:
                break
    except Exception as e:
        logger.exception(e)
    finally:
        monitor_clients.remove(monitor_socket)
        monitor_socket.close()
        logger.warning(f"Monitoring client disconnected: {address}")


def monitor_lidar_data_server(port=8001):
    """
    Start a separate monitoring server to allow clients to view LiDAR data.
    """
    global monitor_lidar_data_clients
    monitor_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    monitor_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    monitor_socket.bind(("0.0.0.0", port))
    monitor_socket.listen()
    logger.info(f"Lidar Data Monitoring server listening on port {port}")

    while True:
        try:
            client_socket, address = monitor_socket.accept()
            threading.Thread(target=handle_monitor_client, args=(client_socket, address, monitor_lidar_data_clients), daemon=True).start()
        except Exception as e:
            logger.exception(f"Error accepting client connection: {e}")
            

def monitor_time_delay_server(port=8002):
    """
    Start a separate monitoring server to allow clients to view Time and delay.
    """
    global monitor_time_delay_clients
    monitor_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    monitor_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    monitor_socket.bind(("0.0.0.0", port))
    monitor_socket.listen()
    logger.info(f"Lidar Data Monitoring server listening on port {port}")

    while True:
        try:
            client_socket, address = monitor_socket.accept()
            threading.Thread(target=handle_monitor_client, args=(client_socket, address, monitor_time_delay_clients), daemon=True).start()
        except Exception as e:
            logger.exception(f"Error accepting client connection: {e}")


def lidar_server_main(lidar_port=8000, monitor_port=[8001, 8002]):
    """
    Start the main server for LiDAR data and monitoring.
    """
    logging_setup()
    threading.Thread(target=monitor_lidar_data_server, args=(monitor_port[0],), daemon=True).start()
    threading.Thread(target=monitor_time_delay_server, args=(monitor_port[1],), daemon=True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind(("0.0.0.0", lidar_port))
        server_socket.listen()
        logger.info(f"LiDAR server listening on port {lidar_port}")

        while True:
            client_socket, _ = server_socket.accept()
            threading.Thread(target=handle_lidar_client, args=(client_socket,), daemon=True).start()

if __name__ == "__main__":
    lidar_server_main()

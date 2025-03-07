import logging.handlers
import socket
import subprocess
import re
import struct
import time
import logging


process = []

# 🔹 **INFO 以下のログのみを `info.log` に記録するフィルタ**
class InfoFilter(logging.Filter):
    def filter(self, record):
        return record.levelno < logging.WARNING  # ERROR 未満（INFO, DEBUG）のみ許可


def logging_setup():
    
    global logger
    
    # ロガー作成
    logger = logging.getLogger("MyLogger")
    logger.setLevel(logging.DEBUG)  # すべてのログを処理対象にする

    # 📂 **Liderデータ（DEBUGのみ）を `lider_data.log` に保存**
    info_handler = logging.handlers.RotatingFileHandler(
        filename=f"/home/lidar/logs/info_logs/info.log", 
        encoding="utf-8",
        maxBytes=1024*1024*10,
        backupCount=5
    )
    info_handler.setLevel(logging.DEBUG)  # DEBUG 以上を記録（後でフィルタで制御）
    # 📂 **エラーログ（ERROR 以上）を `error.log` に保存**
    error_handler = logging.handlers.RotatingFileHandler(
        filename="/home/lidar/logs/error_logs/error.log", 
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

    info_handler.addFilter(InfoFilter())  # フィルタを適用

    # 🔹 **ロガーにハンドラーを追加**
    logger.addHandler(info_handler)
    logger.addHandler(error_handler)
    #logger.addHandler(console_handler)  # コンソール出力
    logger.debug("Logger setuped")


def compress_data(lines, rotation_start_time):
    """
    Compress LiDAR data into binary format with 11-bit and 16-bit fixed fields.
    """
    compressed = bytearray()
    prev_theta = None
    prev_dist = None
    bit_buffer = 0
    bit_count = 0

    def write_bits(value, num_bits):
        """
        Helper function to write `value` into `bit_buffer` with `num_bits` bits.
        """
        nonlocal bit_buffer, bit_count, compressed
        if value < 0:
            value = (1 << num_bits) + value  # 符号付き整数の補数表現

        bit_buffer = (bit_buffer << num_bits) | (value & ((1 << num_bits) - 1))
        bit_count += num_bits

        while bit_count >= 8:
            compressed.append((bit_buffer >> (bit_count - 8)) & 0xFF)
            bit_count -= 8
        bit_buffer &= (1 << bit_count) - 1

    for line in lines:
        match = re.match(r"theta:\s*(\d+\.\d+)\s+Dist:\s*(\d+)", line)
        if match:
            theta = int(float(match.group(1)) * 100)  # Scale theta to integer
            dist = int(match.group(2))  # Distance as integer

            # **🔹 theta と dist が 0 のデータを除外**
            if theta == 0 and dist == 0:
                continue

            if prev_theta is None:
                # 初期値（11ビット角度 + 16ビット距離）
                write_bits(theta, 11)
                write_bits(dist, 16)
            else:
                # 差分（11ビット角度差分 + 16ビット距離差分）
                theta_diff = theta - prev_theta
                dist_diff = dist - prev_dist

                # **🔹 追加: 差分の範囲チェック**
                if not (-1024 <= theta_diff <= 1023) or not (-32768 <= dist_diff <= 32767):
                    logger.warning(f"Warning: Invalid difference detected (Theta: {theta_diff}, Dist: {dist_diff}), skipping this rotation...")
                    return None  # **この回転データを破棄**

                write_bits(theta_diff, 11)
                write_bits(dist_diff, 16)

            prev_theta = theta
            prev_dist = dist

    # バッファに残ったビットをフラッシュ
    if bit_count > 0:
        compressed.append(bit_buffer << (8 - bit_count))

    # 🔹 「一周の開始時刻」を最後に追加
    compressed.extend(struct.pack(">Q", rotation_start_time))  # 64ビット（8バイト）でエンコード

    return compressed


def get_lidar_data():
    """
    Run the LiDAR process and yield lines of valid measurement data in real-time.
    """
    global process
    terminate_lidar_process()  # 🔹 **古いプロセスを終了**
    
    cmd = ["/home/lidar/rplidar_sdk/output/Linux/Release/ultra_simple", "--channel", "--serial", "/dev/ttyUSB0", "460800"]
    process.append(subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))

    for line in iter(process[0].stdout.readline, ""):
        line = line.strip()

        if "theta: 0.00" in line and "Dist: 00000.00" in line and "Q: 0" in line:
            continue

        if re.match(r"theta:\s*\d+\.\d+\s+Dist:\s*\d+", line) or "S" in line:
            yield line


def validate_rotation(theta_list):
    """
    Check if the rotation data is complete and continuous.
    """
    if not theta_list:
        return False  # データがない場合は無効

    theta_list.sort()
    min_theta = theta_list[0] / 100.0
    max_theta = theta_list[-1] / 100.0

    # 角度データが 0° 付近から 360° 付近まで含まれているか
    if min_theta > 10.0 or max_theta < 350.0:
        logger.warning(f"Warning: Invalid rotation detected (theta range abnormal: {min_theta:.2f} - {max_theta:.2f}), skipping... Data Count: {len(theta_list)}")
        return False

    # 角度の連続性チェック（大きな抜けがないか）
    for i in range(len(theta_list) - 1):
        if (theta_list[i + 1] - theta_list[i]) > 1000:  # 10°以上の抜けがある場合
            logger.warning(f"Warning: Large gap detected in theta values, skipping rotation... Data Count: {len(theta_list)}")
            return False

    return True  # 正常なデータ


def process_lidar_data(socket_connection):
    lines = []
    theta_list = []  # 角度データリスト
    rotation_start_time = None  # 一周の開始時刻を記録する変数

    for line in get_lidar_data():
        logger.debug(f"{line}")  # 取得データを表示
        
        if "S" in line:
            if lines:  # もしバッファにデータがあるなら、それを処理
                # 🔹 送信前に異常な週をスキップ（データ数 & 角度のチェック）
                if len(lines) < 300 or len(lines) > 650 or not validate_rotation(theta_list):
                    logger.warning(f"Warning: Skipping this rotation due to invalid data... Data Count: {len(lines)}")
                    lines = []
                    theta_list = []
                    rotation_start_time = int(time.time() * 1e6)
                    continue  # 次の回転へ

                compressed_data = compress_data(lines, rotation_start_time)
                if compressed_data:
                    try:
                        socket_connection.sendall(compressed_data)
                    except Exception as e:
                        logger.exception(f"Error during data transmission: {e}")
                        break

            # 🔹 新しい一周が始まるので、その瞬間の時刻を取得
            rotation_start_time = int(time.time() * 1e6)  # マイクロ秒単位のタイムスタンプ
            lines = []
            theta_list = []  # 角度リストもリセット
        else:
            if rotation_start_time is None:
                rotation_start_time = int(time.time() * 1e6)  # 最初の計測時に時間を取得

            match = re.match(r"theta:\s*(\d+\.\d+)\s+Dist:\s*\d+", line)
            if match:
                theta = int(float(match.group(1)) * 100)  # 角度データを取得
                theta_list.append(theta)  # 角度リストに追加
                lines.append(line)


def terminate_lidar_process():
    global process
    if process:
        for p in process:
            if p.poll() is None:  # まだ動作中なら終了
                p.terminate()
                try:
                    p.wait(timeout=5)  # 終了を待つ（最大5秒）
                except subprocess.TimeoutExpired:
                    logger.warning("Forcing LiDAR process kill...")
                    p.kill()  # 強制終了
                except Exception as e:
                    logger.exception(e)
        process.clear()  # プロセスリストをクリア


def client_main(server_ip, server_port):
    global process
    client_socket = None
    logging_setup()
    while(True):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
                client_socket.settimeout(10)  # 10秒でタイムアウト
                try:
                    client_socket.connect((server_ip, server_port))
                except socket.timeout:
                    logger.error("Connection timed out. Retrying...")
                    continue  # 再試行
                logger.debug("Connected to the server")
                process_lidar_data(client_socket)
        except Exception as e:
            if len(process) > 0:
                terminate_lidar_process()
            logger.exception(e)


if __name__ == "__main__":
#    client_main("192.168.100.152", 8000) # デバック用
    client_main("192.168.201.6", 8000)

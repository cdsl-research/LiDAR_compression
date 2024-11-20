import re
import os
import requests
import logging
import math
import hashlib

logging.basicConfig(level=logging.DEBUG)

# サイズ変換の関数
def format_size(size_bytes):
    if size_bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"

# MD5ハッシュを計算する関数
def calculate_md5(file_content):
    md5_hash = hashlib.md5()
    md5_hash.update(file_content)
    return md5_hash.hexdigest()

# ファイルを送信する関数
# ファイルを送信する関数
def send_binary_file(file_path, server_url):
    with open(file_path, 'rb') as file:
        file_content = file.read()
        file_size = len(file_content)
        print(f"送信するファイルのサイズ: {format_size(file_size)}")
        
        # ファイルのハッシュ値を計算
        file_hash = calculate_md5(file_content)
        print(f"計算されたハッシュ値: {file_hash}")
        
        # バイナリデータをテキスト形式に変換して保存
        with open(f"{file_path}.txt", 'w') as text_file:
            binary_string = ' '.join(f"{byte:08b}" for byte in file_content)  # 各バイトを8ビットの2進数に変換
            text_file.write(binary_string)
            print(f"バイナリデータをテキストファイルとして保存しました: {file_path}.txt")
        
        files = {'file': (os.path.basename(file_path), file_content)}
        data = {'file_hash': file_hash}
        try:
            response = requests.post(server_url, files=files, data=data)
            response.raise_for_status()
            response_json = response.json()
            print(f"ステータスコード: {response.status_code}")
            
            # サーバーからのハッシュ整合性チェックの結果を表示
            if response_json.get("hash_match") is True:
                print("ハッシュ値が一致しました！")
            else:
                print("ハッシュ値が一致しませんでした。データが破損しています。")
                
            return response_json
        except requests.exceptions.RequestException as e:
            print(f"エラーが発生しました: {e}")
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                print(f"エラーの詳細: {e.response.text}")
            return None


# 差分の差分を計算する関数
def calculate_difference(data):
    return [data[i] - data[i - 1] for i in range(1, len(data))]

# バイナリファイルとテキストファイルの書き込み（角度差と距離差を交互に書き込み）
# バイナリファイルとテキストファイルの書き込み（角度差と距離差を交互に書き込み）
def write_combined_bin_file(initial_angle, initial_dist, angle_sequence, dist_sequence, bin_file_path, txt_file_path, values_file_path):
    bit_buffer = 0
    bit_count = 0
    byte_list = []
    bit_string = []  # テキストファイル用のビット列をリストとして初期化

    def write_bits(value, num_bits, is_last=False):
        nonlocal bit_buffer, bit_count, byte_list, bit_string
        if value < 0:
            value = (1 << num_bits) + value
        while num_bits > 0:
            bits_to_write = min(8 - bit_count, num_bits)
            bit_buffer = (bit_buffer << bits_to_write) | ((value >> (num_bits - bits_to_write)) & ((1 << bits_to_write) - 1))
            bit_string.append(f"{(value >> (num_bits - bits_to_write)) & ((1 << bits_to_write) - 1):0{bits_to_write}b}")
            bit_count += bits_to_write
            num_bits -= bits_to_write
            if bit_count == 8:
                byte_list.append(bit_buffer)
                bit_buffer = 0
                bit_count = 0

        # 最後のビットグループの後にスペースを追加するかどうか
        if not is_last:
            bit_string.append(" ")  # 各グループの後にスペースを追加

    # 初期角度と初期距離を書き込む
    write_bits(0, 1)  # 初期角度の符号ビット
    write_bits(int(initial_angle), 9)  # 初期角度は整数に変換して出力
    write_bits(0, 1)  # 初期距離の符号ビット
    write_bits(initial_dist, 15)  # 距離

    # 新しい数値を記録するリスト
    original_values = [int(initial_angle), initial_dist]  # 初期値を追加

    for i in range(len(angle_sequence)):
        angle_diff = angle_sequence[i]
        dist_diff = dist_sequence[i] if i < len(dist_sequence) else 0  # 距離差を使う

        # 角度差の差分をバイナリに変換して書き込む
        if -4 <= angle_diff <= 3:
            write_bits(1, 1)  # 判定ビットを1ビット
            write_bits(angle_diff & 0b111, 3)  # 3ビットで2の補数で表現
        else:
            write_bits(0, 1)  # 判定ビットを0ビット
            write_bits(angle_diff, 9)  # 8ビットで表現

        # 距離差をバイナリに変換して書き込む
        if -4 <= dist_diff <= 3:
            write_bits(1, 1)  # 判定ビットを1ビット
            write_bits(dist_diff & 0b111, 3)  # 3ビットで2の補数で表現
        else:
            write_bits(0, 1)  # 判定ビットを0ビット
            write_bits(dist_diff, 15)  # 15ビットで表現

        # 元の数値を記録
        original_values.append(angle_diff)
        original_values.append(dist_diff)

    if bit_count > 0:
        byte_list.append(bit_buffer << (8 - bit_count))

    # バイナリファイルに書き込む
    with open(bin_file_path, 'wb') as bin_file:
        bin_file.write(bytearray(byte_list))
    
    # テキストファイルにビット列を書き込む（スペースで区切る）
    with open(txt_file_path, 'w') as txt_file:
        # 判定ビットに応じてスペースを追加
        txt_file.write(''.join(bit_string).strip())

    # 新しく出力するファイルに数値を記録
    with open(values_file_path, 'w') as values_file:
        values_file.write(' '.join(map(str, original_values)))

def process_lidar_data(lines, server_url, input_file_path):
    data = []
    theta_prev = None
    dist_prev = None
    rotation_number = 1
    total_binary_size = 0

    os.makedirs("debug", exist_ok=True)
    angle_diff_debug_path = "debug/angle_diff_debug.txt"
    dist_diff_debug_path = "debug/dist_diff_debug.txt"

    with open(angle_diff_debug_path, "w") as angle_debug_file, open(dist_diff_debug_path, "w") as dist_debug_file:
        for line in lines:
            match = re.match(r'\s*S?\s*theta:\s*(\d+\.\d+)\s+Dist:\s*(\d+)\.\d+\s+Q:\s*(\d+)', line)
            if match:
                theta = float(match.group(1))
                dist = int(match.group(2).lstrip('0') or 0)

                if theta_prev is None:
                    # 初期値を設定
                    initial_theta = int(theta * 100)  # スケーリング適用
                    initial_dist = dist
                    theta_prev = theta
                    dist_prev = dist
                    print(f"初期角度: {initial_theta}, 初期距離: {initial_dist}")
                else:
                    theta_diff = round((theta - theta_prev) * 100)  # absは不要、負の値も保持
                    dist_diff = dist - dist_prev
                    data.append((theta_diff, dist_diff))
                    angle_debug_file.write(f"Theta: {theta}, Prev Theta: {theta_prev}, Theta Diff: {theta_diff}\n")
                    dist_debug_file.write(f"Dist: {dist}, Prev Dist: {dist_prev}, Dist Diff: {dist_diff}\n")
                    theta_prev = theta
                    dist_prev = dist

            # 'S'の検出
            if 'S' in line:
                if data:
                    # データを処理する
                    angle_diffs = [diff[0] for diff in data]
                    dist_diffs = [diff[1] for diff in data]

                    angle_diff_of_diff = calculate_difference(angle_diffs)
                    if angle_diffs:
                        angle_diff_of_diff.insert(0, angle_diffs[0])

                    output_dir = "/home/masa/demo2/syuturyoku/outputbin"
                    output_dir2 = "/home/masa/demo2/syuturyoku/values"
                    os.makedirs(output_dir, exist_ok=True)
                    combined_bin_file = os.path.join(output_dir, f'combined_rotation_{rotation_number}.bin')
                    combined_txt_file = os.path.join(output_dir, f'combined_rotation_{rotation_number}.txt')
                    values_txt_file = os.path.join(output_dir2, f'values_rotation_{rotation_number}.txt')

                    # バイナリファイルの書き込み
                    write_combined_bin_file(initial_theta, initial_dist, angle_diff_of_diff, dist_diffs, combined_bin_file, combined_txt_file, values_txt_file)

                    # 圧縮後の合計サイズを計算
                    total_binary_size += os.path.getsize(combined_bin_file)
                    send_binary_file(combined_bin_file, server_url)

                    # 次の回転の準備
                    rotation_number += 1
                    data.clear()  # データをリセット
                    theta_prev = None  # 初期値をリセット
                    dist_prev = None  # 初期値をリセット

    # 元データ（demo.txt）のサイズを取得
    original_file_size = os.path.getsize(input_file_path)

    # 削減率を計算
    compression_ratio = (1 - total_binary_size / original_file_size) * 100

    print(f"元データのサイズ: {format_size(original_file_size)}")
    print(f"圧縮後の合計バイナリサイズ: {format_size(total_binary_size)}")
    print(f"削減率: {compression_ratio:.2f}%")

if __name__ == "__main__":
    # 入力ファイルを指定する
    input_file_path = "/home/masa/demo2/syuturyoku/demo.txt"
    server_url = "http://127.0.0.1:8000/upload_lidar_data/"

    with open(input_file_path, 'r') as input_file:
        lines = input_file.readlines()
        process_lidar_data(lines, server_url, input_file_path)

from fastapi import FastAPI, File, UploadFile, HTTPException, Form
from motor.motor_asyncio import AsyncIOMotorClient
from bson.binary import Binary
import hashlib
import traceback
import os
import logging

app = FastAPI()

# ログ設定
logging.basicConfig(level=logging.INFO)

# MongoDBクライアントの設定
client = AsyncIOMotorClient("mongodb://localhost:27017")
db = client.lidar_data

def decompress_bin_data(byte_data):
    angle_diffs = []
    distance_diffs = []
    bit_buffer = 0
    bit_count = 0
    data_index = 0

    def read_bits(num_bits):
        nonlocal bit_buffer, bit_count, data_index
        value = 0
        while num_bits > 0:
            if bit_count == 0:
                if data_index < len(byte_data):
                    bit_buffer = byte_data[data_index]
                    data_index += 1
                    bit_count = 8
                else:
                    break
            
            bits_to_take = min(bit_count, num_bits)
            value = (value << bits_to_take) | (bit_buffer >> (bit_count - bits_to_take))
            bit_buffer &= (1 << (bit_count - bits_to_take)) - 1
            bit_count -= bits_to_take
            num_bits -= bits_to_take
        return value

    # データを読み取る
    while data_index < len(byte_data) or bit_count > 0:
        # 角度データの処理
        indicator_bit = read_bits(1)
        if indicator_bit == 1:  # 角度差（3ビットの2の補数）
            angle_diff = read_bits(3)
            angle_diff = (angle_diff - 8) if angle_diff >= 4 else angle_diff  # 2の補数変換
            angle_diffs.append(angle_diff)
        else:  # 角度差（8ビット）
            angle_diff = read_bits(9)  # 9ビットで処理
            if angle_diff >= (1 << 8):  # 9ビットでの2の補数変換
                angle_diff -= (1 << 9)
            angle_diffs.append(angle_diff)

        # 距離データの処理
        indicator_bit = read_bits(1)
        if indicator_bit == 1:  # 距離差（3ビットの2の補数）
            dist_diff = read_bits(3)
            dist_diff = (dist_diff - 8) if dist_diff >= 4 else dist_diff  # 2の補数変換
            distance_diffs.append(dist_diff)
        else:  # 距離差（15ビット）
            dist_diff = read_bits(15)
            if dist_diff >= (1 << 14):  # 15ビットの2の補数変換
                dist_diff -= (1 << 15)
            distance_diffs.append(dist_diff)

    # 初期値の設定
    decompressed_sequence = []
    if not angle_diffs or not distance_diffs:
        return decompressed_sequence

    # 初期角度・距離
    current_angle = angle_diffs[0]
    current_distance = distance_diffs[0]
    decompressed_sequence.append((current_angle, current_distance))

    # 2番目の項以降を計算
    for i in range(1, len(angle_diffs)):
        if i == 1:
            current_angle += angle_diffs[i]
            current_distance += distance_diffs[i]
        else:
            current_angle += (angle_diffs[1] + sum(angle_diffs[2:i+1]))
            current_distance += distance_diffs[i]

        # 最後の項目がすでにリストにある場合は追加しない
        if i < len(angle_diffs) - 1 or decompressed_sequence[-1] != (current_angle, current_distance):
            decompressed_sequence.append((current_angle, current_distance))

    return decompressed_sequence


def calculate_md5(file_content):
    md5_hash = hashlib.md5()
    md5_hash.update(file_content)
    return md5_hash.hexdigest()

@app.post("/upload_lidar_data/")
async def upload_lidar_data(file: UploadFile = File(...), file_hash: str = Form(...)):
    try:
        contents = await file.read()
        
        # サーバー側で受信したファイルのハッシュ値を計算
        server_file_hash = calculate_md5(contents)
        
        # クライアント側のハッシュ値と一致するかを確認
        hash_match = server_file_hash == file_hash

        # ログにハッシュの一致状況を出力
        logging.info(f"ファイル名: {file.filename}")
        logging.info(f"サーバー側のハッシュ: {server_file_hash}")
        logging.info(f"クライアント側のハッシュ: {file_hash}")
        logging.info(f"ハッシュ一致: {'一致' if hash_match else '不一致'}")
        
        # ハッシュ値が一致しない場合はエラー
        if not hash_match:
            raise HTTPException(status_code=400, detail="ハッシュ値が一致しません。データが破損しています。")
        
        # バイナリデータを解凍して元の形式に戻す
        decompressed_data = decompress_bin_data(contents)
        
        # 解凍されたデータを "received_data" ディレクトリの "receive_data.txt" に上書き
        received_file_path = os.path.join("received_data", "receive_data.txt")
        os.makedirs(os.path.dirname(received_file_path), exist_ok=True)
        with open(received_file_path, "a") as f:  # "a"モードで追記
            # 解凍されたデータを文字列に変換し、ファイルに書き込む
            f.write("\n".join([f"theta: {angle / 100:.2f} Dist: {distance}" for angle, distance in decompressed_data]) + "\n")

        # 解凍されたデータの最初の10要素をログに出力
        preview_data = decompressed_data[:10]
        preview_str = "\n".join([f"theta: {angle / 100:.2f} Dist: {distance}" for angle, distance in preview_data])
        logging.info(f"解凍されたデータの最初の10要素:\n{preview_str}")

        # データベースに保存する処理
        collection = db["lidar_data"]
        await collection.insert_one({
            "filename": file.filename,
            "data": Binary(contents)  # 元のバイナリデータを保存
        })

        return {"status": "success", "decompressed_data": decompressed_data, "hash_match": hash_match}
    except Exception as e:
        logging.error(f"エラー発生: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="ファイルのアップロード中にエラーが発生しました。")

# サーバーを立ち上げるmain関数
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

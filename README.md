# LiDAR_compression
LiDARデータを圧縮するコードと解凍するサーバー側のコードが入ってます．

##  client.py
このファイルではRPLidar C1から出力されたデータを用います．
input_file_pathにLiDARデータのパスを入れてください．このデータをprocess_lidar_data()で値の読み取り，差分計算，バイナリデータ変換，送信が行われます．
LiDARデータを一周ごとに差分計算を行い送信します．送信時にハッシュ値も一緒に送信します．
デバッグ用で差分計算の結果や送信するbinファイルが出力されます．
実行結果に，圧縮元のデータサイズ，圧縮後のデータサイズ，圧縮率が表示されます

## server.py
このファイルではclient.pyで送られるデータを解凍し差分データを取り出します．受信したバイナリファイルのハッシュ値を計算しハッシュ値の比較を行います．その後，差分データを足し合わせて値を元データに戻していきます．
receive_dataというファイルに解凍結果を出力します．

## test.txt
このファイルにはLiDARデータ1周分が記録されています．

# 実行結果
client.pyでは以下のような表示されます．
圧縮元ファイルサイズ: 12.79 MB
圧縮後のサイズ: 876.54 KB
圧縮率: 6.69%

server.pyでは実行すると以下のようなサーバーが立ち上がった旨の表示があります．
INFO:     Started server process [93104]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
その後，client.pyを実行すると以下のような表示が出力されreceive_data.txtに解凍結果が出力されます．
（一部抜粋）
INFO:root:サーバー側のハッシュ: 78ee13094cd1a033a70ed9b529d857e6
INFO:root:クライアント側のハッシュ: 78ee13094cd1a033a70ed9b529d857e6
INFO:root:ハッシュ一致: 一致

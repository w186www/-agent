"""验证文件上传接口：登录获取 token → 上传图片 → 上传文档 → 验证去重和 avatar 更新。"""
import urllib.request, json, os, hashlib

BASE = "http://127.0.0.1:8000"

def req(method, path, data=None, headers=None):
    body = json.dumps(data).encode() if data else None
    r = urllib.request.Request(BASE + path, data=body, method=method,
                               headers={"Content-Type": "application/json", **(headers or {})})
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

def upload_file(path, token, filename, content_type):
    boundary = "----TestBoundary123"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n"
    ).encode() + open(path, "rb").read() + f"\r\n--{boundary}--\r\n".encode()

    r = urllib.request.Request(
        BASE + "/upload/file",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        resp = urllib.request.urlopen(r)
        return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# 1. 注册测试用户
code, body = req("POST", "/auth/register", {"username": "uploader", "password": "test1234"})
print(f"[1] 注册: HTTP {code}, code={body.get('code')}")
user_id = body["data"]["id"]

# 2. 登录获取 token
code, body = req("POST", "/auth/login", {"username": "uploader", "password": "test1234"})
print(f"[2] 登录: HTTP {code}, code={body.get('code')}")
token = body["data"]["access_token"]

# 3. 创建测试文件
os.makedirs("_test_files", exist_ok=True)
with open("_test_files/test.png", "wb") as f:
    f.write(b"\x89PNG fake image content for testing")
with open("_test_files/test.pdf", "wb") as f:
    f.write(b"%PDF fake document content for testing")

# 4. 上传图片（应更新 avatar）
code, body = upload_file("_test_files/test.png", token, "test.png", "image/png")
print(f"[3] 上传图片: HTTP {code}, code={body.get('code')}")
print(f"    data: {body.get('data')}")

# 5. 验证 avatar 已更新
code, body = req("GET", "/auth/me", headers={"Authorization": f"Bearer {token}"})
print(f"[4] 查询用户: avatar={body['data'].get('avatar')}")

# 6. 上传文档（不应更新 avatar）
code, body = upload_file("_test_files/test.pdf", token, "test.pdf", "application/pdf")
print(f"[5] 上传文档: HTTP {code}, code={body.get('code')}")
print(f"    data: {body.get('data')}")

# 7. 再次上传同一图片（去重：文件已存在，应跳过写入）
code, body = upload_file("_test_files/test.png", token, "test.png", "image/png")
print(f"[6] 重复上传图片: HTTP {code}, code={body.get('code')}")

# 8. 验证文件确实存在于磁盘
stored_name = body["data"]["filename"]
file_path = f"uploads/{user_id}/{stored_name}"
print(f"[7] 文件存在: {os.path.exists(file_path)}")

# 9. 无 token 访问（应 401）
code, body = upload_file("_test_files/test.png", "invalid-token", "test.png", "image/png")
print(f"[8] 无 token 上传: HTTP {code}, code={body.get('code')}")

# 清理
os.remove("_test_files/test.png")
os.remove("_test_files/test.pdf")
os.rmdir("_test_files")
print("\n清理完成")

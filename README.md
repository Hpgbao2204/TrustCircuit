# TrustCircuit

TrustCircuit là prototype kết hợp smart contract, differential privacy, zero-knowledge proof và Windows VBS Enclave cho xử lý dữ liệu ngoài chuỗi.

## Triển khai lại

Yêu cầu: Node.js, Python 3, Visual Studio 2022 x64, Windows SDK 10.0.26100.0 và môi trường VBS Enclave đã cấu hình.

```powershell
npm ci
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm run compile
npm test
```

Sao chép `tee/vbs/TrustCircuitVbs.Local.props.example` thành `tee/vbs/TrustCircuitVbs.Local.props`, điền đường dẫn tooling và certificate local, rồi build:

```powershell
msbuild tee/vbs/TrustCircuitVbs.sln /m /p:Configuration=Debug /p:Platform=x64
powershell -NoProfile -ExecutionPolicy Bypass -File tee/vbs/tests/smoke.ps1
npm run phase7:build
npm run phase7:e2e
```

Biến môi trường và khóa triển khai phải đặt trong `.env`; không commit secrets, private keys, certificate hay dữ liệu riêng tư.

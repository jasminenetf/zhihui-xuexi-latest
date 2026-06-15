# secret_scan误报修复

修复 GitHub Actions 将 `_normalize_spark_api_password` 误判为密钥的问题，保留真实 token 检测能力。

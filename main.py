import os
import uvicorn


if __name__ == "__main__":
    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8051"))
    uvicorn.run("app.main:app", host=host, port=port)

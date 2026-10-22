import uvicorn
from observability import setup_logging

from orders.app import SERVICE, Settings, create_app


def main() -> None:
    settings = Settings.from_env()
    setup_logging(SERVICE, settings.log_level)
    uvicorn.run(
        create_app(settings),
        host="0.0.0.0",
        port=8080,
        log_config=None,
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()

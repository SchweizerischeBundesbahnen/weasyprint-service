import argparse
import logging

from app import weasyprint_controller  # type: ignore

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Weasyprint service")
    parser.add_argument("--port", default=9080, type=int, required=False, help="Service port")
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.INFO)
    logging.info("Weasyprint service listening port: " + str(args.port))
    logging.getLogger().setLevel(logging.WARN)

    weasyprint_controller.start_server(args.port)

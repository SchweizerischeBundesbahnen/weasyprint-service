import time

import docker


def test_container():
    client = docker.from_env()

    image, _ = client.images.build(path=".", tag="weasyprint_service", buildargs={"APP_IMAGE_VERSION": "1.0.0"})
    container = client.containers.run(image=image, detach=True, name="weasyprint_service", ports={"9080": 9080})
    time.sleep(5)
    logs = container.logs()
    container.stop()
    container.remove()

    assert logs == b"INFO:root:Weasyprint service listening port: 9080\n"

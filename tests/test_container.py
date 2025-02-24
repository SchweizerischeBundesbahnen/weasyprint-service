import time

import docker


def test_container():
    client = docker.from_env()

    image, _ = client.images.build(path=".", tag="wps", buildargs={"APP_IMAGE_VERSION": "1.0.0"})
    container = client.containers.run(image=image, detach=True, name="wps", ports={"9081": 9081})
    time.sleep(5)
    logs = container.logs()
    container.stop()
    container.remove()

    assert logs == b"INFO:root:Weasyprint service listening port: 9080\n"


test_container()

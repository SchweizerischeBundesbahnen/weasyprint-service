# Copy uv from official image (version matches .tool-versions)
FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv-source

# ---------------------------------------------------------------- Visio stage
# Alpine 3.24 has libvisio 0.1.10, not the 0.1.7 weasyvsdx is tested with, and emf2svg only in edge/testing.
# So this stage builds them from their upstream releases, checked by their SHA-256: librevenge 0.0.5 and
# libvisio 0.1.7 from the LibreOffice project, and libemf2svg 1.1.0. Debian builds the same releases without
# patches. The libraries they link come from Alpine: their sonames go to /opt/visio/needed, which the runtime
# installs with apk.
FROM alpine:3.24.3@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a AS visio
# perl generates the token table of libvisio, the image does not keep it. musl has no argp, which emf2svg-conv
# parses its options with.
# hadolint ignore=DL3018
RUN apk add --no-cache argp-standalone bash binutils boost-dev build-base cmake fontconfig-dev freetype-dev gperf icu-dev libpng-dev libxml2-dev perl pkgconf zlib-dev
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ADD --checksum=sha256:5892ca6796f7a2a93d580832e907e849b19d980b40d326a283b18877ab6de0c5 \
    https://dev-www.libreoffice.org/src/librevenge-0.0.5.tar.bz2 /src/
ADD --checksum=sha256:8faf8df870cb27b09a787a1959d6c646faa44d0d8ab151883df408b7166bea4c \
    https://dev-www.libreoffice.org/src/libvisio/libvisio-0.1.7.tar.xz /src/
ADD --checksum=sha256:ad48d2de9d1f4172aca475d9220bbd152b7280f98642db561ee6688faf50cd1e \
    https://github.com/kakwa/libemf2svg/archive/refs/tags/1.1.0.tar.gz /src/libemf2svg-1.1.0.tar.gz
ENV PREFIX=/opt/visio \
    PKG_CONFIG_PATH=/opt/visio/lib/pkgconfig \
    LDFLAGS="-Wl,-rpath,/opt/visio/lib"
WORKDIR /src
RUN tar xf librevenge-0.0.5.tar.bz2 && tar xf libvisio-0.1.7.tar.xz && tar xf libemf2svg-1.1.0.tar.gz
WORKDIR /src/librevenge-0.0.5
RUN ./configure --prefix="${PREFIX}" --disable-static --disable-tests --disable-werror --without-docs && \
    make -j"$(nproc)" && make install-strip
WORKDIR /src/libvisio-0.1.7
RUN ./configure --prefix="${PREFIX}" --disable-static --disable-tests --disable-werror --without-docs && \
    make -j"$(nproc)" && make install-strip
# libemf2svg asks for a CMake older than 3.5, which CMake 4 refuses without a policy minimum. Its CMake
# expects argp in libc, so emf2svg-conv links the static libargp of argp-standalone.
WORKDIR /src
RUN cmake -S libemf2svg-1.1.0 -B emf2svg-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
        -DCMAKE_CXX_STANDARD_LIBRARIES=-largp \
        -DCMAKE_INSTALL_PREFIX="${PREFIX}" -DCMAKE_INSTALL_RPATH="${PREFIX}/lib" && \
    cmake --build emf2svg-build -j"$(nproc)" && \
    cmake --install emf2svg-build --strip
# Only the tools weasyvsdx runs and their libraries stay, with the license of each project: vsd2xhtml, vsd2raw,
# whose output places the text, and emf2svg-conv. The sonames they need from outside /opt/visio go to
# /opt/visio/needed.
RUN find "${PREFIX}/bin" -type f ! -name vsd2xhtml ! -name vsd2raw ! -name emf2svg-conv -delete && \
    rm -rf "${PREFIX}/include" "${PREFIX}/lib/pkgconfig" "${PREFIX}/share" "${PREFIX}"/lib/*.la && \
    for project in librevenge-0.0.5 libvisio-0.1.7; do \
        mkdir -p "${PREFIX}/licenses/${project}" && cp "${project}/COPYING".* "${PREFIX}/licenses/${project}/"; \
    done && \
    mkdir -p "${PREFIX}/licenses/libemf2svg-1.1.0" && cp libemf2svg-1.1.0/LICENSE "${PREFIX}/licenses/libemf2svg-1.1.0/" && \
    ls "${PREFIX}/lib" > /tmp/own-libraries && \
    readelf --dynamic "${PREFIX}"/bin/* "${PREFIX}"/lib/*.so.*.* | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | sort -u | \
        grep -vxF -f /tmp/own-libraries > "${PREFIX}/needed" && \
    "${PREFIX}/bin/vsd2xhtml" --version

# ---------------------------------------------------------------- fonts stage
# The fonts of the Debian image and the fontconfig rules which choose among them, so the PDFs come out as
# they did on Debian. The fonts of another distribution change them.
# Carlito and Caladea replace the Calibri and Cambria Visio drawings ask for. Symbola draws the symbols Word
# documents take from Wingdings and Symbol.
FROM debian:trixie-slim@sha256:62bd423aeee912639ca8ee681c2b762cb3e25137e0a92b20be455898a9f034ad AS fonts
# hadolint ignore=DL3008
RUN apt-get update && \
    apt-get --yes --no-install-recommends install \
    fontconfig \
    fonts-crosextra-caladea \
    fonts-crosextra-carlito \
    fonts-dejavu \
    fonts-freefont-ttf \
    fonts-ipafont-gothic \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-noto-cjk-extra \
    fonts-noto-color-emoji \
    fonts-symbola \
    fonts-tlwg-loma-otf \
    fonts-unifont \
    fonts-wqy-zenhei

# The packages which own a file under the font directories, their copyright files, a dpkg database of these
# packages alone for the SBOM, and the active fontconfig rules, with fonts.conf including them by an absolute
# path for FONTCONFIG_FILE. A font linked through /etc/alternatives is linked to its file, the runtime has no
# alternatives.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN dpkg-query --search '/etc/fonts/*' '/usr/share/fonts/*' '/usr/share/fontconfig/*' | cut -d: -f1 | tr ',' '\n' | \
        tr -d ' ' | sort -u > /font-packages && \
    test -s /font-packages && \
    mkdir -p /licenses /sbom-root/etc /sbom-root/var/lib/dpkg && \
    cp /etc/os-release /sbom-root/etc/os-release && \
    xargs dpkg-query --status < /font-packages > /sbom-root/var/lib/dpkg/status && \
    while read -r package; do \
        mkdir -p "/licenses/${package}" "/sbom-root/usr/share/doc/${package}" && \
        cp "/usr/share/doc/${package}/copyright" "/licenses/${package}/" && \
        cp "/usr/share/doc/${package}/copyright" "/sbom-root/usr/share/doc/${package}/"; \
    done < /font-packages && \
    mkdir -p /fontconfig/conf.d && \
    cp --dereference /etc/fonts/conf.d/*.conf /fontconfig/conf.d/ && \
    sed 's#<include ignore_missing="yes">conf.d</include>#<include ignore_missing="yes">/opt/weasyprint/fontconfig/conf.d</include>#' \
        /etc/fonts/fonts.conf > /fontconfig/fonts.conf && \
    grep -q '/opt/weasyprint/fontconfig/conf.d' /fontconfig/fonts.conf && \
    find /usr/share/fonts -lname '/etc/alternatives/*' -exec sh -c 'ln -sf "$(readlink -f "$1")" "$1"' sh {} \;

# A CycloneDX SBOM of the font packages with their Debian purls and licenses: the apk database of the final
# image does not know them.
FROM anchore/syft:v1.55.0@sha256:4cc92b64ca74ffca4c94d4c8fcc01f217731375300be14d0b6eeb2e82eaa110a AS fonts-sbom
ENV SYFT_FILE_METADATA_SELECTION=none
COPY --from=fonts /sbom-root /sbom-root
RUN ["/syft", "scan", "dir:/sbom-root", "--select-catalogers", "dpkg", "--source-name", "debian-fonts", "-o", "cyclonedx-json=/tmp/debian-fonts.cdx.json"]

# -------------------------------------------------------------- runtime stage
# Alpine fixes its stable branch in point releases, where Debian keeps unfixed findings in the libraries the
# service loads. Its libc is musl: Python comes from the musl build of uv, the packages from musllinux wheels.
FROM alpine:3.24.3@sha256:be2656061b536c1883c4034790e21d0a09c5aaaf51968b89368a3c0371ea2c9a

# Copy uv binary from source stage
COPY --from=uv-source /uv /usr/local/bin/uv

# Pango for WeasyPrint, and harfbuzz-subset, so WeasyPrint subsets fonts with HarfBuzz. bash for entrypoint.sh,
# fontconfig for fc-cache, mimalloc for malloc. The libraries the Visio converters link are installed by
# their soname.
COPY --from=visio /opt/visio /opt/visio
SHELL ["/bin/sh", "-o", "pipefail", "-c"]
# hadolint ignore=DL3018,SC2046
RUN apk add --no-cache \
    bash \
    fontconfig \
    harfbuzz-subset \
    mimalloc2 \
    pango \
    $(sed 's/^/so:/' /opt/visio/needed) && \
    ln -s /opt/visio/bin/vsd2xhtml /opt/visio/bin/vsd2raw /opt/visio/bin/emf2svg-conv /usr/local/bin/ && \
    mkdir -p /usr/share/doc && \
    mv /opt/visio/licenses/* /usr/share/doc/ && \
    rmdir /opt/visio/licenses && \
    test "$(vsd2xhtml --version)" = "vsd2xhtml 0.1.7"

# The fonts of the Debian image, their copyright files and their SBOM. No apk package owns these paths.
# FONTCONFIG_FILE selects Debian's rules.
COPY --from=fonts /usr/share/fonts /usr/share/fonts
COPY --from=fonts /licenses /usr/share/doc
COPY --from=fonts-sbom /tmp/debian-fonts.cdx.json /usr/share/doc/debian-fonts.cdx.json
COPY --from=fonts /fontconfig /opt/weasyprint/fontconfig
ENV FONTCONFIG_FILE=/opt/weasyprint/fontconfig/fonts.conf

# The malloc of musl is slow for the many small allocations of Pango and cairo. An empty LD_PRELOAD at
# docker run restores it.
ENV LD_PRELOAD=/usr/lib/libmimalloc.so.2

ARG APP_IMAGE_VERSION=0.0.0
ENV WORKING_DIR="/opt/weasyprint" \
    WEASYPRINT_SERVICE_VERSION=${APP_IMAGE_VERSION} \
    PORT=9080 \
    METRICS_PORT=9180 \
    LOG_LEVEL=INFO

# Create non-root user early (before creating directories that need ownership)
RUN adduser -D -u 1000 -s /bin/bash appuser

# Create and configure logging directory (owned by appuser)
RUN mkdir -p ${WORKING_DIR}/logs && \
    chown appuser:appuser ${WORKING_DIR}/logs && \
    chmod 777 ${WORKING_DIR}/logs && \
    mkdir -p /tmp/strictdoc && \
    chown -R appuser:appuser /tmp/strictdoc

WORKDIR ${WORKING_DIR}

# Copy Python version file and dependency files
COPY .tool-versions pyproject.toml uv.lock ./

# Install Python via uv to /opt/python (version from .tool-versions file).
# pip comes with it, and nothing in the image uses it: uv installs the packages.
# Removed here, so the scanners do not report the packages it vendors.
ENV UV_PYTHON_INSTALL_DIR=/opt/python
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN PYTHON_VERSION=$(awk '/^python / {print $2}' .tool-versions) && \
    uv python install --no-cache "${PYTHON_VERSION}" && \
    rm -rf /opt/python/*/lib/python3.*/site-packages/pip* /opt/python/*/lib/python3.*/ensurepip/_bundled /opt/python/*/bin/pip*

# The image has no compiler, so every package installs from a wheel: --no-build
# fails the build on a package without one for this Python. --no-cache keeps the
# downloads out of the image, the venv holds what runs.
RUN uv sync --frozen --no-dev --no-install-project --no-build --no-cache

# Create build timestamp
RUN BUILD_TIMESTAMP="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" && \
    echo "${BUILD_TIMESTAMP}" > "${WORKING_DIR}/.build_timestamp"

# Copy application code and resources (owned by appuser for potential runtime writes)
COPY --chown=appuser:appuser ./app/*.py ${WORKING_DIR}/app/
COPY --chown=appuser:appuser ./app/static/ ${WORKING_DIR}/app/static/
COPY --chown=appuser:appuser ./app/resources/ ${WORKING_DIR}/app/resources/
COPY --chown=appuser:appuser ./entrypoint.sh ${WORKING_DIR}/entrypoint.sh
COPY --chown=appuser:appuser ./healthcheck.sh ${WORKING_DIR}/healthcheck.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh ${WORKING_DIR}/healthcheck.sh

# Add venv to PATH
ENV PATH="/opt/weasyprint/.venv/bin:$PATH" \
    PYTHONPATH=${WORKING_DIR}

# Replace the German hyphenation dictionaries bundled with Pyphen (LibreOffice
# patterns, frozen at 2017-01-12) with the newer dehyph-exptl patterns
# (dehyphn-x 2024-02-28). These fix single-letter mis-hyphenation such as
# "Über-g-ang" -> "Über-gang" and cover reformed orthography for DE/AT/CH.
# The same reformed pattern set is used for de_DE, de_AT and de_CH. The MIT
# notice is shipped alongside the data (dehyph-exptl requires it to travel with
# redistributed copies, which the image is).
COPY dictionaries/hyph_de_dehyphn-x-2024-02-28.dic ${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic
COPY dictionaries/LICENSE.dehyph-exptl ${WORKING_DIR}/dictionaries/LICENSE.dehyph-exptl
RUN DICT_DIR="$(python -c 'import os, pyphen; print(os.path.dirname(str(pyphen.LANGUAGES["de_DE"])))')" && \
    cp "${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic" "${DICT_DIR}/hyph_de_DE.dic" && \
    cp "${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic" "${DICT_DIR}/hyph_de_AT.dic" && \
    cp "${WORKING_DIR}/dictionaries/hyph_de_dehyphn-x-2024-02-28.dic" "${DICT_DIR}/hyph_de_CH.dic"

# Verify WeasyPrint is installed and working
RUN weasyprint --version

# Selawik, the open fallback Microsoft made for Segoe UI, which Visio drawings ask for. Neither Debian nor
# Alpine has a package of it: the release of microsoft/Selawik, checked by its SHA-256. Its fonts carry no
# license text, which the SIL Open Font License asks to travel with each copy, so the license of the release
# goes along.
ADD --checksum=sha256:3f62c51e05e3b5a1e6241cf92a371f0be2ea1183aa87b30718bbd40832a8d423 \
    https://github.com/microsoft/Selawik/releases/download/1.01/Selawik_Release.zip /tmp/selawik.zip
ADD --checksum=sha256:77b7c2506d4efb22e09c8ccf10159f4956eab3ef7c007fef95de136bcf45300c \
    https://raw.githubusercontent.com/microsoft/Selawik/1.01/LICENSE.txt /usr/local/share/fonts/selawik/LICENSE.txt
RUN python -c "import zipfile; archive = zipfile.ZipFile('/tmp/selawik.zip'); archive.extractall('/usr/local/share/fonts/selawik', [name for name in archive.namelist() if name.endswith('.ttf')])" && \
    chmod 644 /usr/local/share/fonts/selawik/LICENSE.txt && \
    rm /tmp/selawik.zip && \
    fc-cache --force && \
    test -n "$(fc-list Selawik)" && test -n "$(fc-list Carlito)"

# Switch to non-root user (numeric uid:gid of appuser, resolvable by any host)
USER 1000:1000

EXPOSE ${PORT}
EXPOSE ${METRICS_PORT}

# Add healthcheck
HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=3 \
    CMD ["/bin/sh", "-c", "./healthcheck.sh || exit 1"]

ENTRYPOINT ["./entrypoint.sh"]

# Security and metadata labels
LABEL maintainer="SBB Polarion Team <polarion-opensource@sbb.ch>" \
      org.opencontainers.image.title="WeasyPrint Service (Alpine)" \
      org.opencontainers.image.description="API service for WeasyPrint document processing" \
      org.opencontainers.image.vendor="SBB" \
      org.opencontainers.image.security.caps.drop="ALL" \
      org.opencontainers.image.security.no-new-privileges="true"

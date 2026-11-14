# Copy uv from official image (version matches .tool-versions)
FROM ghcr.io/astral-sh/uv:0.13.8@sha256:5cc1805e2426484abca4ad46ea783bab281fdb225fd82d8ce6d66a81254bac85 AS uv-source

# ---------------------------------------------------------------- Visio stage
# UBI has no libvisio and no emf2svg, so this stage builds them from their upstream releases, checked by their
# SHA-256: librevenge 0.0.5 and libvisio 0.1.7, the release weasyvsdx is tested with, from the LibreOffice
# project, and libemf2svg 1.1.0. Debian builds the same releases without patches. UBI has no boost-devel and no
# gperf either: the headers of boost 1.83, the release of RHEL 10, and gperf 3.1 come from their releases too.
# The libraries the tools link come from UBI: their sonames go to /opt/visio/needed, which the rootfs stage
# installs by the capability of each.
FROM registry.access.redhat.com/ubi10/ubi:latest@sha256:65201965dbdf33aecf3796ba454684be29083708fadb6335507b86a56d2df06c AS visio
# hadolint ignore=DL3041
RUN dnf --assumeyes --setopt=install_weak_deps=0 install \
        binutils bzip2 cmake diffutils findutils fontconfig-devel freetype-devel gcc-c++ libicu-devel \
        libpng-devel libxml2-devel make perl-interpreter pkgconf-pkg-config tar xz zlib-ng-compat-devel && \
    dnf clean all
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ADD --checksum=sha256:6478edfe2f3305127cffe8caf73ea0176c53769f4bf1585be237eb30798c3b8e \
    https://archives.boost.io/release/1.83.0/source/boost_1_83_0.tar.bz2 /src/
ADD --checksum=sha256:588546b945bba4b70b6a3a616e80b4ab466e3f33024a352fc2198112cdbb3ae2 \
    https://mirrors.kernel.org/gnu/gperf/gperf-3.1.tar.gz /src/
ADD --checksum=sha256:5892ca6796f7a2a93d580832e907e849b19d980b40d326a283b18877ab6de0c5 \
    https://dev-www.libreoffice.org/src/librevenge-0.0.5.tar.bz2 /src/
ADD --checksum=sha256:8faf8df870cb27b09a787a1959d6c646faa44d0d8ab151883df408b7166bea4c \
    https://dev-www.libreoffice.org/src/libvisio/libvisio-0.1.7.tar.xz /src/
ADD --checksum=sha256:ad48d2de9d1f4172aca475d9220bbd152b7280f98642db561ee6688faf50cd1e \
    https://github.com/kakwa/libemf2svg/archive/refs/tags/1.1.0.tar.gz /src/libemf2svg-1.1.0.tar.gz
WORKDIR /src
# gperf generates the token table of libvisio and boost is used by its headers alone: neither reaches the image
RUN tar xf gperf-3.1.tar.gz && tar xf librevenge-0.0.5.tar.bz2 && tar xf libvisio-0.1.7.tar.xz && tar xf libemf2svg-1.1.0.tar.gz && \
    mkdir -p /opt/boost/include && \
    tar xjf boost_1_83_0.tar.bz2 -C /opt/boost/include --strip-components=1 boost_1_83_0/boost
WORKDIR /src/gperf-3.1
RUN ./configure --prefix=/usr/local && make -j"$(nproc)" && make install
ENV PREFIX=/opt/visio \
    PKG_CONFIG_PATH=/opt/visio/lib/pkgconfig \
    CPPFLAGS="-I/opt/boost/include" \
    LDFLAGS="-Wl,-rpath,/opt/visio/lib"
WORKDIR /src/librevenge-0.0.5
RUN ./configure --prefix="${PREFIX}" --disable-static --disable-tests --disable-werror --without-docs && \
    make -j"$(nproc)" && make install-strip
WORKDIR /src/libvisio-0.1.7
RUN ./configure --prefix="${PREFIX}" --disable-static --disable-tests --disable-werror --without-docs && \
    make -j"$(nproc)" && make install-strip
# libemf2svg asks for a CMake older than 3.5, which CMake 4 refuses without a policy minimum
WORKDIR /src
RUN cmake -S libemf2svg-1.1.0 -B emf2svg-build -DCMAKE_BUILD_TYPE=Release -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
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
# they did on Debian. UBI has few of these fonts: Noto CJK, Unifont, Symbola, Carlito, Caladea and others are
# missing. Carlito and Caladea replace the Calibri and Cambria Visio drawings ask for. Symbola draws the
# symbols Word documents take from Wingdings and Symbol. The fontconfig package of UBI requires
# default-fonts-core-sans, whose Noto Sans would take sans-serif from DejaVu Sans: the rules reject the fonts
# of that package, which stay installed so that no file of an rpm package changes.
FROM debian:trixie-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 AS fonts
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
    printf '%s\n' '<?xml version="1.0"?>' '<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">' '<fontconfig>' \
        '  <selectfont><rejectfont>' \
        '    <glob>/usr/share/fonts/google-noto-vf/*</glob>' '    <glob>/usr/share/fonts/redhat-vf/*</glob>' \
        '  </rejectfont></selectfont>' '</fontconfig>' > /fontconfig/conf.d/01-reject-ubi-fonts.conf && \
    sed 's#<include ignore_missing="yes">conf.d</include>#<include ignore_missing="yes">/opt/weasyprint/fontconfig/conf.d</include>#' \
        /etc/fonts/fonts.conf > /fontconfig/fonts.conf && \
    grep -q '/opt/weasyprint/fontconfig/conf.d' /fontconfig/fonts.conf && \
    find /usr/share/fonts -lname '/etc/alternatives/*' -exec sh -c 'ln -sf "$(readlink -f "$1")" "$1"' sh {} \;

# A CycloneDX SBOM of the font packages with their Debian purls and licenses: the rpm database of the final
# image does not know them.
FROM anchore/syft:v1.55.0@sha256:4cc92b64ca74ffca4c94d4c8fcc01f217731375300be14d0b6eeb2e82eaa110a AS fonts-sbom
ENV SYFT_FILE_METADATA_SELECTION=none
COPY --from=fonts /sbom-root /sbom-root
RUN ["/syft", "scan", "dir:/sbom-root", "--select-catalogers", "dpkg", "--source-name", "debian-fonts", "-o", "cyclonedx-json=/tmp/debian-fonts.cdx.json"]

# ---------------------------------------------------------------- rootfs stage
# The runtime is UBI micro: bash and coreutils, but no package manager. Its root filesystem is filled here with
# dnf --installroot from the full UBI image, so the rpm database of the runtime lists every package, and dnf,
# microdnf and rpm stay out of it. Pango for WeasyPrint, with HarfBuzz, whose package carries
# libharfbuzz-subset, fontconfig for fc-cache, and the libraries the Visio tools link, by their soname.
FROM registry.access.redhat.com/ubi10/ubi-micro:latest@sha256:8488f5ec082768a01d1ce4e0ef3878f782a40ff6d233afa74bc23d4e740620a4 AS micro
FROM registry.access.redhat.com/ubi10/ubi:latest@sha256:65201965dbdf33aecf3796ba454684be29083708fadb6335507b86a56d2df06c AS rootfs
COPY --from=micro / /rootfs
COPY --from=visio /opt/visio /rootfs/opt/visio
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
# hadolint ignore=DL3041
RUN mapfile -t needed < <(sed 's/$/()(64bit)/' /rootfs/opt/visio/needed) && \
    dnf --assumeyes --installroot=/rootfs --releasever=10 --setopt=install_weak_deps=0 --nodocs install \
        fontconfig harfbuzz pango "${needed[@]}" && \
    dnf --installroot=/rootfs clean all && \
    rm -rf /rootfs/var/cache/dnf /rootfs/var/log/dnf* && \
    useradd --root /rootfs --uid 1000 --user-group --create-home --shell /bin/bash appuser && \
    ln -s /opt/visio/bin/vsd2xhtml /opt/visio/bin/vsd2raw /opt/visio/bin/emf2svg-conv /rootfs/usr/local/bin/ && \
    mkdir -p /rootfs/usr/share/doc && \
    mv /rootfs/opt/visio/licenses/* /rootfs/usr/share/doc/ && \
    rmdir /rootfs/opt/visio/licenses

# ---------------------------------------------------------------- python stage
# Python and the venv are installed where awk and the other tools exist, at the paths the runtime uses.
FROM registry.access.redhat.com/ubi10/ubi:latest@sha256:65201965dbdf33aecf3796ba454684be29083708fadb6335507b86a56d2df06c AS python
COPY --from=uv-source /uv /usr/local/bin/uv
WORKDIR /opt/weasyprint
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

# Replace the German hyphenation dictionaries bundled with Pyphen (LibreOffice
# patterns, frozen at 2017-01-12) with the newer dehyph-exptl patterns
# (dehyphn-x 2024-02-28). These fix single-letter mis-hyphenation such as
# "Über-g-ang" -> "Über-gang" and cover reformed orthography for DE/AT/CH.
# The same reformed pattern set is used for de_DE, de_AT and de_CH. The MIT
# notice is shipped alongside the data (dehyph-exptl requires it to travel with
# redistributed copies, which the image is).
COPY dictionaries/hyph_de_dehyphn-x-2024-02-28.dic dictionaries/LICENSE.dehyph-exptl /opt/weasyprint/dictionaries/
RUN DICT_DIR="$(.venv/bin/python -c 'import os, pyphen; print(os.path.dirname(str(pyphen.LANGUAGES["de_DE"])))')" && \
    for region in DE AT CH; do cp dictionaries/hyph_de_dehyphn-x-2024-02-28.dic "${DICT_DIR}/hyph_de_${region}.dic"; done

# Selawik, the open fallback Microsoft made for Segoe UI, which Visio drawings ask for. Neither Debian nor UBI
# has a package of it: the release of microsoft/Selawik, checked by its SHA-256. Its fonts carry no license
# text, which the SIL Open Font License asks to travel with each copy, so the license of the release goes along.
ADD --checksum=sha256:3f62c51e05e3b5a1e6241cf92a371f0be2ea1183aa87b30718bbd40832a8d423 \
    https://github.com/microsoft/Selawik/releases/download/1.01/Selawik_Release.zip /tmp/selawik.zip
ADD --checksum=sha256:77b7c2506d4efb22e09c8ccf10159f4956eab3ef7c007fef95de136bcf45300c \
    https://raw.githubusercontent.com/microsoft/Selawik/1.01/LICENSE.txt /selawik/LICENSE.txt
RUN .venv/bin/python -c "import zipfile; archive = zipfile.ZipFile('/tmp/selawik.zip'); archive.extractall('/selawik', [name for name in archive.namelist() if name.endswith('.ttf')])" && \
    chmod 644 /selawik/LICENSE.txt

# -------------------------------------------------------------- runtime stage
# Red Hat backports fixes into the releases of RHEL 10, so the scanners report no high or critical finding
# where Debian keeps unfixed ones in the libraries the service loads. The runtime has no package manager.
FROM scratch
COPY --from=rootfs /rootfs /

# Copy uv binary from source stage
COPY --from=uv-source /uv /usr/local/bin/uv

# The fonts of the Debian image, their copyright files and their SBOM. No rpm package owns these paths.
# FONTCONFIG_FILE selects Debian's rules.
COPY --from=fonts /usr/share/fonts /usr/share/fonts
COPY --from=fonts /licenses /usr/share/doc
COPY --from=fonts-sbom /tmp/debian-fonts.cdx.json /usr/share/doc/debian-fonts.cdx.json
COPY --from=fonts /fontconfig /opt/weasyprint/fontconfig
COPY --from=python /selawik /usr/local/share/fonts/selawik
ENV FONTCONFIG_FILE=/opt/weasyprint/fontconfig/fonts.conf

ARG APP_IMAGE_VERSION=0.0.0
ENV WORKING_DIR="/opt/weasyprint" \
    WEASYPRINT_SERVICE_VERSION=${APP_IMAGE_VERSION} \
    PORT=9080 \
    METRICS_PORT=9180 \
    LOG_LEVEL=INFO \
    UV_PYTHON_INSTALL_DIR=/opt/python

WORKDIR ${WORKING_DIR}

# Copy Python version file and dependency files
COPY .tool-versions pyproject.toml uv.lock ./
COPY --from=python /opt/python /opt/python
COPY --from=python /opt/weasyprint/.venv /opt/weasyprint/.venv
COPY --from=python /opt/weasyprint/dictionaries /opt/weasyprint/dictionaries

# Create and configure logging directory (owned by appuser), and the build timestamp
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN mkdir -p ${WORKING_DIR}/logs /tmp/strictdoc && \
    chown 1000:1000 ${WORKING_DIR}/logs /tmp/strictdoc && \
    chmod 777 ${WORKING_DIR}/logs && \
    date -u +'%Y-%m-%dT%H:%M:%SZ' > "${WORKING_DIR}/.build_timestamp"

# Copy application code and resources (owned by appuser for potential runtime writes)
COPY --chown=1000:1000 ./app/*.py ${WORKING_DIR}/app/
COPY --chown=1000:1000 ./app/static/ ${WORKING_DIR}/app/static/
COPY --chown=1000:1000 ./app/resources/ ${WORKING_DIR}/app/resources/
COPY --chown=1000:1000 ./entrypoint.sh ${WORKING_DIR}/entrypoint.sh
COPY --chown=1000:1000 ./healthcheck.sh ${WORKING_DIR}/healthcheck.sh
RUN chmod +x ${WORKING_DIR}/entrypoint.sh ${WORKING_DIR}/healthcheck.sh

# Add venv to PATH
ENV PATH="/opt/weasyprint/.venv/bin:$PATH" \
    PYTHONPATH=${WORKING_DIR}

# Verify WeasyPrint, the fonts of Visio drawings and libvisio
RUN weasyprint --version && \
    fc-cache --force && \
    test -n "$(fc-list Selawik)" && test -n "$(fc-list Carlito)" && \
    test "$(vsd2xhtml --version)" = "vsd2xhtml 0.1.7"

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
      org.opencontainers.image.title="WeasyPrint Service (UBI)" \
      org.opencontainers.image.description="API service for WeasyPrint document processing" \
      org.opencontainers.image.vendor="SBB" \
      org.opencontainers.image.security.caps.drop="ALL" \
      org.opencontainers.image.security.no-new-privileges="true"

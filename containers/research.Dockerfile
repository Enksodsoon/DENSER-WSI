FROM python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36

ARG OPENSLIDE_REF=51de3070fad7c3871fd299b3d6042ea535716160
ARG VIPS_REF=e01a4797cabe77d457fdfa7d776b7a7e7ca6d6a7
ARG JPEG_TURBO_REF=c85e6b905bf237038faa936dab160ebfc5da0344
ARG OPENJPEG_REF=bbbe3a092256511ec9056a7ad204f9db42a87264
ARG LIBJXL_REF=a7a9c787341cf703dede03c2009fa460cae5e5df
ARG LIBAVIF_REF=cc1ba78b3c37066e57f2879b2696d4d7fbc1244b
ARG ZSTD_REF=ac66b19e6bd6b83238bf008eecc1298105298532

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SOURCE_DATE_EPOCH=0

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates cmake git meson ninja-build pkg-config \
      libaom-dev libarchive-dev libcairo2-dev libcfitsio-dev libexif-dev libexpat1-dev \
      libffi-dev libglib2.0-dev libheif-dev liblcms2-dev libpng-dev \
      libsqlite3-dev libtiff-dev libwebp-dev libxml2-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/src

RUN git clone https://github.com/facebook/zstd.git && cd zstd && \
    git checkout "$ZSTD_REF" && \
    cmake -S build/cmake -B out -G Ninja -DCMAKE_BUILD_TYPE=Release && \
    cmake --build out && cmake --install out

RUN git clone https://github.com/libjpeg-turbo/libjpeg-turbo.git && cd libjpeg-turbo && \
    git checkout "$JPEG_TURBO_REF" && \
    cmake -S . -B out -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_INSTALL_PREFIX=/usr/local -DWITH_TOOLS=ON && \
    cmake --build out && cmake --install out

RUN git clone https://github.com/uclouvain/openjpeg.git && cd openjpeg && \
    git checkout "$OPENJPEG_REF" && \
    cmake -S . -B out -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_CODEC=ON && \
    cmake --build out && cmake --install out

RUN git clone --recurse-submodules https://github.com/libjxl/libjxl.git && cd libjxl && \
    git checkout "$LIBJXL_REF" && git submodule update --init --recursive && \
    cmake -S . -B out -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DBUILD_TESTING=OFF -DJPEGXL_ENABLE_TOOLS=ON && \
    cmake --build out && cmake --install out

RUN git clone --recurse-submodules https://github.com/AOMediaCodec/libavif.git && cd libavif && \
    git checkout "$LIBAVIF_REF" && git submodule update --init --recursive && \
    cmake -S . -B out -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DAVIF_CODEC_AOM=SYSTEM -DAVIF_LIBYUV=OFF \
      -DAVIF_BUILD_APPS=ON -DAVIF_BUILD_TESTS=OFF && \
    cmake --build out && cmake --install out

RUN git clone https://github.com/openslide/openslide.git && cd openslide && \
    git checkout "$OPENSLIDE_REF" && \
    meson setup out --buildtype=release && meson compile -C out && meson install -C out

RUN git clone https://github.com/libvips/libvips.git && cd libvips && \
    git checkout "$VIPS_REF" && \
    meson setup out --buildtype=release -Dintrospection=disabled && \
    meson compile -C out && meson install -C out && \
    ldconfig && rm -rf /tmp/src

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

ENTRYPOINT ["python", "-m", "denser.cli"]

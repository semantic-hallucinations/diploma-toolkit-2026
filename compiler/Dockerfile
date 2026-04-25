FROM debian:bookworm-slim@sha256:f9c6a2fd2ddbc23e336b6257a5245e31f996953ef06cd13a59fa0a1df2d5c252

ARG TARGETARCH
ARG TL_REPOSITORY=https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/2025/tlnet-final

ENV PATH=/opt/texlive/bin/current:$PATH

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates curl perl xz-utils python3 \
  && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
  case "$TARGETARCH" in \
    amd64) tl_arch="x86_64-linux" ;; \
    arm64) tl_arch="aarch64-linux" ;; \
    *) echo "Unsupported Docker architecture: $TARGETARCH" >&2; exit 1 ;; \
  esac; \
  mkdir -p /tmp/install-tl; \
  curl -fsSL "$TL_REPOSITORY/install-tl-unx.tar.gz" \
    | tar -xz -C /tmp/install-tl --strip-components=1; \
  { \
    echo "selected_scheme scheme-basic"; \
    echo "TEXDIR /opt/texlive"; \
    echo "TEXMFCONFIG ~/.texlive/texmf-config"; \
    echo "TEXMFHOME ~/texmf"; \
    echo "TEXMFLOCAL /opt/texlive/texmf-local"; \
    echo "TEXMFSYSCONFIG /opt/texlive/texmf-config"; \
    echo "TEXMFSYSVAR /opt/texlive/texmf-var"; \
    echo "TEXMFVAR ~/.texlive/texmf-var"; \
    echo "instopt_adjustpath 0"; \
    echo "instopt_adjustrepo 0"; \
    echo "instopt_letter 0"; \
    echo "instopt_portable 0"; \
    echo "instopt_write18_restricted 1"; \
    echo "tlpdbopt_autobackup 0"; \
    echo "tlpdbopt_create_formats 1"; \
    echo "tlpdbopt_desktop_integration 0"; \
    echo "tlpdbopt_file_assocs 0"; \
    echo "tlpdbopt_generate_updmap 1"; \
    echo "tlpdbopt_install_docfiles 0"; \
    echo "tlpdbopt_install_srcfiles 0"; \
    echo "tlpdbopt_post_code 1"; \
    echo "tlpdbopt_sys_bin /usr/local/bin"; \
    echo "tlpdbopt_sys_info /usr/local/share/info"; \
    echo "tlpdbopt_sys_man /usr/local/share/man"; \
  } > /tmp/texlive.profile; \
  /tmp/install-tl/install-tl -profile /tmp/texlive.profile -repository "$TL_REPOSITORY"; \
  ln -s "/opt/texlive/bin/$tl_arch" /opt/texlive/bin/current; \
  rm -rf /tmp/install-tl /tmp/texlive.profile

RUN tlmgr option repository "$TL_REPOSITORY" \
  && tlmgr option docfiles 0 \
  && tlmgr option srcfiles 0 \
  && tlmgr install \
    amsfonts \
    amsmath \
    babel-russian \
    bigfoot \
    caption \
    catchfile \
    cm-super \
    cyrillic \
    enumitem \
    etoolbox \
    extsizes \
    fancyhdr \
    float \
    footmisc \
    fp \
    framed \
    fvextra \
    gensymb \
    geometry \
    graphics \
    hyperref \
    hyphen-russian \
    hyphenat \
    latex2pydata \
    lastpage \
    lh \
    lineno \
    makecell \
    microtype \
    minted \
    multirow \
    natbib \
    pgfopts \
    setspace \
    siunitx \
    textcase \
    tocloft \
    tools \
    totcount \
    ulem \
    upquote \
    xcolor \
    xstring \
  && updmap-sys --enable Map=cm-super-t2a.map \
  && updmap-sys \
  && fmtutil-sys --byfmt pdflatex \
  && rm -rf /tmp/*

COPY compile.sh /usr/local/bin/diploma-compile
RUN chmod +x /usr/local/bin/diploma-compile

WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/diploma-compile"]

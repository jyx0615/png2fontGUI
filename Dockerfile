# Build stage — compiles the TS orchestrator and Tailwind CSS
FROM node:22-bookworm-slim AS builder

WORKDIR /app

# The committed package-lock.json's optional-dependency (esbuild platform
# binaries) metadata isn't readable by Node 18's bundled npm@10 — `npm ci`
# fails with "Missing: esbuild@... from lock file" even though the lockfile
# itself is valid (npm@11, as used locally, installs from it without issue).
RUN npm install -g npm@11

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json tailwind.config.js postcss.config.js ./
COPY src ./src
COPY static ./static

RUN npm run build

# Runtime stage — Node (orchestrator) + Python/FontForge/nanoemoji (font tools),
# since the pipeline shells out to python3/fontforge/addsvg/nanoemoji/ttf2woff2
# for every job phase (see CLAUDE.md's "hybrid architecture").
FROM node:22-bookworm-slim

WORKDIR /app

# fontforge isn't available for Alpine, hence the Debian-based image above.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fontforge \
    python3 \
    python3-pip \
    curl \
    ca-certificates \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# nanoemoji's pngquant-cli dependency has no prebuilt wheel for this platform
# and compiles from source; Debian bookworm's apt rustc (1.63) is too old for
# its dependency unicode-width (needs wrapping_add_signed, stabilized 1.66),
# so install a current toolchain via rustup instead.
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable

# ttf2woff2 is a Node-based CLI tool (npm install -g), same as setup_env.sh does locally.
RUN npm install -g ttf2woff2

# svgcleaner has no Linux wheel/package — download the prebuilt binary (same
# release setup_env.sh's macOS binary is a local dev copy of). png2svg.py
# invokes it as "./svgcleaner" relative to its cwd, which is /app (Node's
# subprocess calls don't override cwd), so it must live at /app/svgcleaner.
RUN curl -sL https://github.com/RazrFalcon/svgcleaner/releases/download/v0.9.5/svgcleaner_linux_x86_64_0.9.5.tar.gz \
    | tar -xz -C /app svgcleaner && chmod +x /app/svgcleaner

# Python font-tooling dependencies (vtracer, opentypesvg/addsvg, fontTools, Pillow, numpy).
COPY requirements.txt ./
RUN pip install --no-cache-dir --break-system-packages -r requirements.txt

# nanoemoji is vendored as a git subtree (editable install, matches setup_env.sh).
# Its setup.py uses setuptools-scm to derive the version from git describe,
# but the subtree squash discards nanoemoji's own tag history (and a plain
# COPY has no .git metadata anyway) — pin a version explicitly instead,
# matching the upstream release vendored in (see CLAUDE.md).
COPY nanoemoji ./nanoemoji
ENV SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NANOEMOJI=0.15.9
RUN pip install --no-cache-dir --break-system-packages -e ./nanoemoji

# Node production dependencies (same npm@11 upgrade as the builder stage — see comment there).
RUN npm install -g npm@11
COPY package.json package-lock.json ./
RUN npm ci --only=production

# Built app + Python scripts + assets the pipeline reads at runtime.
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/static ./static
COPY python ./python
COPY config.toml ./

ENV NODE_ENV=production
ENV PORT=8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD wget --quiet --tries=1 --spider http://localhost:8000/health || exit 1

EXPOSE 8000

CMD ["npm", "start"]

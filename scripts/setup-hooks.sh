#!/bin/sh
# 이 저장소의 커밋 훅(.githooks/)을 활성화한다. 클론 후 1회.
set -e
cd "$(dirname "$0")/.."
git config core.hooksPath .githooks
echo "core.hooksPath = .githooks  (pre-commit 활성)"

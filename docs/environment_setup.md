# Environment Setup

本文件用于让使用者或 AI 在新机器上判断当前系统、创建 `env/` 目录、安装依赖，并完成最小 smoke test。

**约束：** skill 主流程不应自动加载本文件；仅当用户询问环境安装、Playwright-cli、Node.js、`env/.venv`、Codex CLI、Ubuntu 或跨平台兼容性时再读取。

## 1. 适用范围

当前支持两类宿主环境：

- **Ubuntu / Debian-based Linux**：推荐生产环境
- **macOS**：推荐开发/调试环境

若系统不属于上述范围，应明确说明「当前环境不在支持范围内」。

## 2. 目标结果

完成后，仓库内应具备如下运行时布局（均在 `env/` 下）：

```text
env/
├── .venv/
├── node/
│   ├── package.json
│   └── node_modules/
└── ms-playwright/
```

- `env/.venv/`：Python 运行时
- `env/node/`：Node 本地部署
- `env/ms-playwright/`：Playwright 浏览器缓存

**禁止：**

- 不要把上述运行时复制到仓库根目录
- 不要在根目录创建 `.venv/` 或 `node_modules/`
- 不要在根目录保留 `*.egg-info/`、`build/`、`dist/` 等安装产物

## 3. 执行原则

1. 先判断当前真实系统，再执行对应分支
2. 不要复用其他机器上的 `env/.venv`
3. 不要复用已存在但不符合格式的 `env/`、`env/node/package.json` 或 `env/.venv`
4. 若缺失，应重建为符合格式要求的目录
5. 若仓库没有 `requirements.txt` 或根级 `package.json`，不要擅自假设；以 `pyproject.toml` 为准
6. 环境搭建过程中不要在仓库根目录保留临时产物；若某步不可避免产生，搭建完成后必须删除

## 4. 当前仓库实际依赖

### 4.1 系统层依赖

- `git`
- `curl`
- `ripgrep`
- Ubuntu 下的 `Xvfb`（仅 Linux 需要）

### 4.2 Python 层依赖

仓库根目录 `pyproject.toml` 当前声明：

- `duckdb`, `openpyxl`, `pandas`, `numpy`, `scipy`, `matplotlib`, `seaborn`
- `PyYAML>=6.0`, `playwright`, `beautifulsoup4`, `lxml`, `tiktoken`

此外还需要补装：

- `requests`
- `curl_cffi`

### 4.3 Node 层依赖

仓库级 Node 运行时统一放在 `env/node/`：

- 全局安装 `@openai/codex`
- 全局安装 `@playwright/cli`
- 在 `env/node/` 下安装 `playwright`

`skills/playwright-cli/scripts/proxy-access.js` 依赖：

```js
const { chromium } = require('playwright');
```

### 4.4 浏览器层依赖

- Python 侧浏览器：供 `env/.venv` 内的 `playwright` 使用
- Node 侧浏览器：供 `playwright-cli` 和 `proxy-access.js` 使用
- 浏览器缓存统一放在 `env/ms-playwright/`

## 5. 版本策略

- **Node.js**：当前最新 LTS
- **Python**：优先 3.12，兼容下限 `>=3.10`
- **uv**：最新稳定版
- **Codex CLI / Playwright CLI**：`@latest`

## 6. 先判断当前系统

```bash
uname -s
uname -m
python3 --version || true
node -v || true
npm -v || true
command -v apt || true
command -v brew || true
```

- `Linux` + `apt` → Ubuntu/Debian 路径
- `Darwin` + `brew` → macOS 路径
- 其他 → 停止并说明不支持

## 7. Ubuntu / Debian 环境搭建

### 7.1 安装系统基础依赖

```bash
sudo apt update
sudo apt install -y \
  curl git ca-certificates build-essential xz-utils \
  ripgrep tmux xvfb x11-utils
sudo apt install -y pkg-config libffi-dev libssl-dev
```

### 7.2 安装 Node.js（nvm）

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
nvm install --lts
nvm alias default 'lts/*'
```

### 7.3 安装 uv

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"
```

### 7.4 安装 Codex CLI

```bash
npm install -g @openai/codex@latest
codex --version
```

安装后必须完成认证：`codex --help` → 登录 → 再次运行 `codex` 确认无 auth 错误。

### 7.5 安装 Playwright CLI

```bash
npm install -g @playwright/cli@latest
playwright-cli --help
```

### 7.6 创建仓库级 Node 运行时

```bash
cd <REPO_ROOT>
mkdir -p env/node env/ms-playwright
cat > env/node/package.json <<'EOF'
{
  "name": "codex-agent-product-info-template-pro-env",
  "private": true,
  "description": "Repo-local Node dependencies for proxy/browser helpers.",
  "dependencies": {
    "playwright": "^1.58.2"
  }
}
EOF
npm install --prefix env/node
```

### 7.7 安装 Playwright 浏览器

```bash
sudo npx --prefix env/node playwright install-deps chromium
PLAYWRIGHT_BROWSERS_PATH="$PWD/env/ms-playwright" \
  npx --prefix env/node playwright install chromium chrome
```

### 7.8 配置 Xvfb

```bash
which Xvfb
mkdir -p /tmp/.X11-unix
chmod 1777 /tmp/.X11-unix
export DISPLAY=:99
Xvfb :99 -screen 0 1920x1080x24 >/tmp/xvfb.log 2>&1 &
xdpyinfo | head -n 1
```

## 8. macOS 环境搭建

```bash
brew install ripgrep
# 安装 Node (nvm)、uv、Codex CLI、Playwright CLI 同 Ubuntu 步骤
# 创建 env/node 同 7.6
npm install --prefix env/node
PLAYWRIGHT_BROWSERS_PATH="$PWD/env/ms-playwright" \
  npx --prefix env/node playwright install chromium chrome
```

macOS 通常不需要 Xvfb。

## 9. 创建 Python 运行时

```bash
cd <REPO_ROOT>
mkdir -p env
uv python install 3.12
uv venv --python 3.12 env/.venv
source env/.venv/bin/activate
uv pip install \
  duckdb openpyxl pandas numpy scipy matplotlib seaborn \
  PyYAML playwright beautifulsoup4 lxml tiktoken requests curl_cffi
source env/.venv/bin/activate
PLAYWRIGHT_BROWSERS_PATH="$PWD/env/ms-playwright" playwright install chromium
```

## 10. 最小验收

### 10.1 通用验收

```bash
node -v && npm -v && uv --version
codex --help && codex --version
rg --version && playwright-cli --help
test -f env/node/package.json
./env/.venv/bin/python --version
codex  # 确认可进入 CLI，无 auth 错误
```

### 10.2 Python 运行时验收

```bash
./env/.venv/bin/python <<'PY'
import yaml, pandas, numpy, scipy, matplotlib, seaborn
import bs4, lxml, tiktoken, requests
from curl_cffi import requests as curl_requests
from playwright.sync_api import sync_playwright
print("python deps ok")
PY
```

### 10.3 Node Playwright 验收

```bash
node <<'JS'
const path = require('path');
const { createRequire } = require('module');
const req = createRequire(path.resolve('env/node/package.json'));
const { chromium } = req('playwright');
console.log('node-playwright-ok', typeof chromium.launch);
JS
```

### 10.4 项目运行入口验收

```bash
./env/.venv/bin/python skills/taojin_v3_crawl_skill/scripts/worktree_cli.py --help
./env/.venv/bin/python skills/site-seed-discovery/scripts/discover_seed_urls.py --help
node --check skills/playwright-cli/scripts/proxy-access.js
```

## 11. 交付边界

应交付：仓库源码、`README.md`、`AGENTS.md`、本文件。

不应交付：`env/.venv/`、`env/node/node_modules/`、`env/ms-playwright/`、`.playwright-cli/`、`*.egg-info/`、`build/`、`dist/`。

## 12. 常见问题

### 12.1 nvm: command not found

```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"
```

### 12.2 uv: command not found

```bash
export PATH="$HOME/.local/bin:$PATH"
```

### 12.3–12.4 缺少 Python 包

```bash
source env/.venv/bin/activate
uv pip install curl_cffi requests
```

### 12.5 Python playwright 报错

```bash
source env/.venv/bin/activate
uv pip install playwright
PLAYWRIGHT_BROWSERS_PATH="$PWD/env/ms-playwright" playwright install chromium
```

### 12.6 Codex CLI 认证失败

先修复登录，再继续主流程。

### 12.7 Ubuntu headed 打不开

检查 `DISPLAY`、`Xvfb`、`xdpyinfo`。

### 12.8 不要跨系统复用 env/.venv

macOS 和 Ubuntu 必须分别重建 `env/.venv` 并重新安装依赖。

.PHONY: help install dev uninstall test build upload upload-test clean

help: ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## 从源码安装（pipx，隔离环境）
	pipx install . --force

dev: ## 开发模式安装（pip install -e .，可编辑）
	pip3 install -e .

uninstall: ## 卸载（pipx uninstall）
	pipx uninstall miniclaw

test: ## 运行全部测试
	python3 -m pytest tests/ -v

build: clean ## 构建 dist/ 包（sdist + wheel）
	python3 -m build

upload: ## 上传到 PyPI（需要先 make build）
	twine upload dist/*

upload-test: ## 上传到 Test PyPI
	twine upload --repository testpypi dist/*

clean: ## 清理构建产物
	rm -rf dist/ build/ *.egg-info miniclaw.egg-info

VENV := .venv
PY   := $(VENV)/bin/python
CMAKE := $(VENV)/bin/cmake
NINJA := $(VENV)/bin/ninja

.PHONY: bootstrap build test clean

bootstrap:
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r requirements-dev.txt
	$(VENV)/bin/pip install -q -e .

build: bootstrap
	$(CMAKE) -G Ninja -B build \
	  -DCMAKE_MAKE_PROGRAM=$(abspath $(NINJA)) \
	  -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ .
	$(CMAKE) --build build

test: build
	$(VENV)/bin/pytest tests -v

clean:
	rm -rf build

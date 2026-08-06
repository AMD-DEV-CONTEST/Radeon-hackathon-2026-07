CXX = g++
CXXFLAGS = -std=c++17 -O2 -Wall

all: aisearch

aisearch: main.cpp search_engine.cpp
	$(CXX) $(CXXFLAGS) -o aisearch main.cpp search_engine.cpp

clean:
	rm -f aisearch

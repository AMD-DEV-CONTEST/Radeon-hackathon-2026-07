#!/usr/bin/env python3
"""Unified path setup and debug printer for all track3 scripts.

Import this module FIRST in every script to ensure:
  - PROJECT_ROOT is set correctly (auto-detect from script location)
  - PYTHONPATH includes PROJECT_ROOT
  - All relative paths resolve from PROJECT_ROOT
  - Debug info is printed once at startup

Usage:
    from scripts.setup_paths import ensure_paths, print_env_info
    PROJECT_ROOT = ensure_paths()
    print_env_info(PROJECT_ROOT, model_path, config_path, env_name)
"""
import os
import sys


def ensure_paths():
    """Set up PROJECT_ROOT and PYTHONPATH, return PROJECT_ROOT.

    Detects whether we're running from:
      - /workspace/radeon-repo (remote GPU)
      - amd-physical-ai-soccer (local dev)
      - any other directory containing the project code
    """
    # Walk up to find the project root (directory containing configs/ or soccer_env*.py)
    here = os.path.dirname(os.path.abspath(__file__))
    project_root = None

    # Try: scripts/ is one level below root
    candidate = os.path.dirname(here)
    if os.path.exists(os.path.join(candidate, "configs")) or \
       os.path.exists(os.path.join(candidate, "soccer_env_hierarchical.py")) or \
       os.path.exists(os.path.join(candidate, "envs", "soccer_env.py")):
        project_root = candidate

    # Try: scripts/ is two levels below root (amd-physical-ai-soccer/scripts/)
    if project_root is None:
        candidate = os.path.dirname(os.path.dirname(here))
        if os.path.exists(os.path.join(candidate, "configs")):
            project_root = candidate

    # Fallback: use current working directory
    if project_root is None:
        project_root = os.getcwd()

    # Insert into sys.path if not already there
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Also add src/ if it exists (for match_3v3.policy etc.)
    src_path = os.path.join(project_root, "src")
    if os.path.isdir(src_path) and src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Change to project root so relative paths in configs resolve
    os.chdir(project_root)

    return project_root


def print_env_info(project_root, model_path=None, config_path=None, env_name=None):
    """Print debug info about the execution environment."""
    print("=" * 70)
    print("[setup_paths] Environment Info")
    print("=" * 70)
    print(f"  CWD:          {os.getcwd()}")
    print(f"  PROJECT_ROOT: {project_root}")
    print(f"  PYTHONPATH:   {':'.join(sys.path[:5])}")
    if model_path:
        abs_model = os.path.abspath(model_path)
        exists = os.path.exists(abs_model)
        print(f"  Model path:   {abs_model}")
        print(f"  Model exists: {exists}")
    if config_path:
        abs_cfg = os.path.abspath(config_path)
        exists = os.path.exists(abs_cfg)
        print(f"  Config path:  {abs_cfg}")
        print(f"  Config exists: {exists}")
    if env_name:
        print(f"  Env class:   {env_name}")
    print("=" * 70)


def safe_import_env():
    """Import the hierarchical soccer env with fallback handling.

    Tries multiple import paths:
      1. envs.soccer_env_hierarchical (if envs/ package exists)
      2. soccer_env_hierarchical (top-level, as in /workspace/radeon-repo)
      3. soccer_env_v4.SoccerEnv (fallback to v4 env)
    """
    # Try hierarchical env first
    try:
        try:
            from envs.soccer_env_hierarchical import SoccerEnvHierarchical
            return SoccerEnvHierarchical, "envs.soccer_env_hierarchical.SoccerEnvHierarchical"
        except ImportError:
            from soccer_env_hierarchical import SoccerEnvHierarchical
            return SoccerEnvHierarchical, "soccer_env_hierarchical.SoccerEnvHierarchical"
    except ImportError as e:
        print(f"[setup_paths] WARNING: Could not import SoccerEnvHierarchical: {e}")
        print(f"[setup_paths] sys.path = {sys.path}")
        raise

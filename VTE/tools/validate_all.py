import os
import sys
import subprocess

def run_script(script_name):
    print(f"\n{'='*70}")
    print(f"EXECUTANDO: {script_name}")
    print(f"{'='*70}\n")
    
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    
    # We use subprocess to run the scripts independently
    result = subprocess.run([sys.executable, script_path], capture_output=False)
    
    if result.returncode == 0:
        print(f"\n✅ {script_name} concluiu com SUCESSO.")
        return True
    else:
        print(f"\n❌ {script_name} FALHOU (código {result.returncode}).")
        return False

def main():
    print("="*70)
    print("INICIANDO SUÍTE DE VALIDAÇÃO VTE")
    print("="*70)
    
    scripts = [
        "validate_kernel_fusion.py",
        "validate_hip_graphs.py",
        "benchmark_performance.py",
        "validate_integration.py"
    ]
    
    success = True
    for script in scripts:
        if not run_script(script):
            success = False
            # Can choose to break or continue; we continue to show all results
            
    print("\n" + "="*70)
    if success:
        print("✅ TODOS OS TESTES DE VALIDAÇÃO PASSARAM!")
    else:
        print("❌ ALGUNS TESTES DE VALIDAÇÃO FALHARAM. Verifique os logs acima.")
    print("="*70)
    
    return success

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

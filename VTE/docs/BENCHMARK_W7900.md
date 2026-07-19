# Benchmark VTE no AMD Radeon PRO W7900 (Hackathon AMD, cloud)

Data: 2026-07-19
Instância: cloud AMD (`radeon-global.anruicloud.com`, instância `u-9248-2d58da42`), acesso via SSH direto (`sshd` precisou ser instalado manualmente -- não vinha por padrão na imagem) e via JupyterLab (usado só para descobrir o SSH inicialmente).

Este documento registra os números REAIS medidos nesta sessão -- carregamento
de modelo, geração de texto (tok/s) e telemetria de GPU (VRAM, temperatura,
potência, utilização) -- para uma primeira execução completa e funcional da
VTE em Linux nativo, num hardware que é o alvo oficial da competição.

## Ambiente

| Item | Valor |
|---|---|
| GPU | AMD Radeon PRO W7900 (`gfx1100`, RDNA3), nome reportado pelo driver: "AMD Radeon Graphics" (genérico -- ver seção de bugs) |
| VRAM total | 49136 MB (~48 GiB) |
| Compute Units | 96 CUs (confirmado via `rocminfo` e via VTE) |
| CPU | AMD EPYC 9334 32-Core (2 sockets visíveis via `rocminfo`, 128 vCPUs total) |
| RAM | 503 GiB |
| Disco (`/workspace`) | 98 GiB, 93 GiB livres no início |
| SO | Ubuntu 24.04.4 LTS |
| Kernel driver | ROCk module version 6.16.13 |
| ROCm | 7.2.1 |
| HIP | 7.2.53211-e1a6bc5663, `hipcc` disponível |
| amd-smi | 26.2.2+e1a6bc5663 |
| Python (venv do projeto) | 3.12.3 |
| Rede | Provedor cloud chinês -- `huggingface.co`/`pypi.org` diretos ficaram inacessíveis (timeout na camada TCP); resolvido usando `hf-mirror.com` para o download do modelo e o mirror Tsinghua para pip (já era o fallback padrão do script de boot da instância) |

## Modelo testado

**Granite 4.1 30B, quantização Q8_0** (`ibm-granite/granite-4.1-30b-GGUF:granite-4.1-30b-Q8_0.gguf`)
- Repositório oficial: https://huggingface.co/ibm-granite/granite-4.1-30b-GGUF
- Arquivo usado: https://huggingface.co/ibm-granite/granite-4.1-30b-GGUF/resolve/main/granite-4.1-30b-Q8_0.gguf
- Baixado via espelho (`huggingface.co` direto ficou inacessível nesta rede, ver seção Ambiente): https://hf-mirror.com/ibm-granite/granite-4.1-30b-GGUF/resolve/main/granite-4.1-30b-Q8_0.gguf
- SHA256: `2f772a60949ab40144bca249a5a38f7fa530d6b6649c14b8b6395c4cd64ef396` (calculado nesta sessão, promovido a `GRANITE_4_1_30B_EXPECTED_HASH` em `vte/config.py`)
- Arquivo real: 30674969824 bytes (~28.57 GiB)
- 64 camadas (`block_count`), hidden=4096, heads=32, kv_heads=8, head_dim=128, ffn=32768, contexto nativo 131072
- Escolhido deliberadamente por ser um modelo maior/mais capaz do que os curados anteriormente (3B) -- só viável de testar de verdade numa GPU com VRAM grande como a W7900

**Qwen2.5 1.5B Instruct, quantização Q4_K_M** (usado só na comparação VTE vs llama.cpp, ver seção correspondente) (`bartowski/Qwen2.5-1.5B-Instruct-GGUF:Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`)
- Repositório: https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF
- Arquivo usado: https://huggingface.co/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
- Baixado via espelho: https://hf-mirror.com/bartowski/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
- Arquivo real: ~941 MB

**Qwen2.5 32B Instruct, quantização Q4_K_M** (`bartowski/Qwen2.5-32B-Instruct-GGUF:Qwen2.5-32B-Instruct-Q4_K_M.gguf`)
- Repositório: https://huggingface.co/bartowski/Qwen2.5-32B-Instruct-GGUF
- Arquivo usado: https://huggingface.co/bartowski/Qwen2.5-32B-Instruct-GGUF/resolve/main/Qwen2.5-32B-Instruct-Q4_K_M.gguf
- Baixado via espelho: https://hf-mirror.com/bartowski/Qwen2.5-32B-Instruct-GGUF/resolve/main/Qwen2.5-32B-Instruct-Q4_K_M.gguf
- SHA256: `2e5f6daea180dbc59f65a40641e94d3973b5dbaa32b3c0acf54647fa874e519e` (calculado nesta sessão, promovido a `QWEN2_5_32B_EXPECTED_HASH` em `vte/config.py`)
- Arquivo real: 19851336576 bytes (~18.49 GiB)
- 64 camadas (`block_count`), hidden=5120, heads=40, kv_heads=8, contexto nativo 32768, arquitetura `qwen2` (mesma família já suportada pelo Qwen2.5 1.5B/7B, sem nenhuma mudança de kernel/mapper necessária)
- Segundo modelo pedido pelo usuário depois do Granite 30B, especificamente pra continuar validando modelos grandes na W7900

**Llama 3.1 8B Instruct, quantização Q4_K_M** (`bartowski/Meta-Llama-3.1-8B-Instruct-GGUF:Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf`) -- já registrado e validado numa sessão anterior (mesmo hash/tamanho já em `vte/config.py`), reaproveitado aqui pra testar arquitetura `llama` (terceira família diferente de `qwen2`/`granite`) num tamanho intermediário
- Repositório: https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF
- Arquivo usado: https://huggingface.co/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
- Baixado via espelho: https://hf-mirror.com/bartowski/Meta-Llama-3.1-8B-Instruct-GGUF/resolve/main/Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf
- Arquivo real: 4920739232 bytes (~4.58 GiB), SHA256 já confirmado em sessão anterior (`LLAMA3_1_8B_EXPECTED_HASH`)

## Bugs reais encontrados e corrigidos nesta sessão

Todos os três a seguir só foram descobertos porque, pela primeira vez nesta
sessão, a VTE rodou em hardware Linux + ROCm real (todo o desenvolvimento
anterior foi feito às cegas contra o SDK Windows, sem uma máquina Linux+ROCm
disponível). Ver `vte/bridge/dll_discovery.py` e `hip_runtime.py` para os
comentários que já registravam essa limitação antes de hoje.

### 1. `hipGetDeviceProperties` resolvia pro símbolo ABI errado

`libamdhip64.so` exporta 3 símbolos versionados para essa função
(`nm -D libamdhip64.so`):
```
hipGetDeviceProperties@@hip_4.2          <- ABI antiga (pré uuid/luid/gcnArchName)
hipGetDevicePropertiesR0000@@hip_4.2     <- idêntico ao acima
hipGetDevicePropertiesR0600@@hip_6.0     <- ABI atual, com gcnArchName
```
O código chamava o nome nu (`lib.hipGetDeviceProperties`), que o linker
resolve pro símbolo **antigo**, incompatível com a struct `hipDeviceProp_t`
mantida à mão no arquivo (que já tentava seguir o layout novo). Resultado:
todo campo depois de `name` lia do offset errado. `multiProcessorCount`
retornava lixo (38911 numa GPU com 32 CUs reais -- já havia um workaround
via `hipDeviceGetAttribute` pra esse campo específico, documentado no
código); `gcnArchName` não existia na struct antiga, então a detecção de
arquitetura caía sempre no fallback por nome comercial.

**Impacto direto**: GPUs workstation/server (W7900 incluída) reportam o nome
genérico `"AMD Radeon Graphics"` via ROCm -- o fallback por nome comercial
não bate com nenhuma entrada de `GPU_ARCH_MAP`, e o código caía silenciosamente
no `DEFAULT_GPU_ARCH`. Nesta GPU o fallback coincidiu por acaso com o valor
certo (`gfx1100`); numa workstation de outra família (ex. W6800, `gfx1030`)
teria escolhido a arquitetura ERRADA sem erro nenhum.

**Correção**: struct `hipDeviceProp_t` reescrita campo a campo a partir do
header real (`/opt/rocm/include/hip/hip_runtime_api.h`, ROCm 7.2.1), symbol
binding trocado para `hipGetDevicePropertiesR0600` explícito, e
`get_gpu_architecture()`/`_select_device_index()` passaram a priorizar
`gcnArchName` (ISA real reportada pelo driver) sobre o nome comercial.
Validado ao vivo nos dois lados: RX 7600 (Windows) -> `gfx1102` correto,
W7900 (Linux) -> `gfx1100` correto, sem mais warning de fallback.

### 2. Teto de alocação única fixo em 8GB, calibrado só pra RX 7600

`MAX_ALLOCATION_SIZE = 8 * 1024**3` em `vte/config.py` era uma constante
fixa (o total de VRAM da RX 7600, único hardware jamais testado até hoje).
A VTE aloca pesos+KV+arena+buffers como **um slab único** via `hipMalloc`
(`VTE_GIANT_SLAB`) -- ao tentar carregar o Granite 30B (slab de ~29.9GB),
essa checagem rejeitava a alocação mesmo sobrando ~19GB de VRAM livre na
GPU de 48GB.

**Correção**: o teto agora compara contra `self._vram_total` (VRAM física
real do device, medida em `initialize()`), não mais uma constante. A
checagem de 95% (`VRAM_USAGE_LIMIT`) logo abaixo já era o guard real e
correto contra OOM; o teto fixo era só sanidade redundante e desatualizada.

### 3. Sanitizer não conhecia o Granite 30B

O sanitizer valida GGUFs por whitelist de nome de arquivo por
arquitetura/variante (`vte/compiler/sanitizer.py::SUPPORTED_ARCHITECTURES`).
Só o Granite 3B estava registrado. Adicionada a variante
`granite-4.1-30b-Q8_0.gguf` (block_count=64) com constantes de tamanho
(`GRANITE_4_1_30B_SIZE_MIN/MAX`) em `vte/config.py`, e o checkpoint curado
`granite-4.1:30b-q8_0` em `vte/core/downloader.py` e `vte/core/model.py`.

Todos os três consertos foram validados com a suíte de testes local inteira
(`pytest tests/`, 78 passed) antes e depois, além do teste ao vivo contra o
hardware real.

## Resultado: carregamento do modelo (Granite 4.1 30B)

| Etapa | Tempo |
|---|---|
| Carregamento completo (`from_pretrained`, inclui sanitização + injeção de pesos + compilação/captura do HIP Graph) | 41.2 - 47.9s (2 execuções) |
| Injeção de pesos na VRAM (mmap, 578 tensores) | ~22-24s |
| VRAM ocupada pelos pesos | 29249.5 MB |
| KV Cache Pool alocado | 1024.0 MB |
| Activation Arena | 307.2 MB |
| HIP Graph (modo decode) | 899 kernels gravados com sucesso |

## Resultado: geração de texto (tok/s real, medido) (Granite 4.1 30B)

Três prompts em português, `max_tokens=150`, `context_length=4096`, medidos
via os campos `prefill_duration_ttft`/`decoding_speed_tps` que `generate()`
já expõe (usados pelo `vte-server` na resposta OpenAI-compatible). Execução
repetida duas vezes de forma independente (reload completo do modelo em
cada uma) para confirmar consistência:

| Prompt | Tokens gerados | TTFT (prefill, s) | Decode (tok/s) | Motivo de parada |
|---|---|---|---|---|
| Curto ("explique RDNA3 em uma frase") | 62-67 | 0.63 | 20.38-20.40 | `stop` (EOS natural) |
| Médio (parágrafo sobre atenção) | 150 | 1.35 | 20.13 | `length` (max_tokens) |
| Longo (história curta de ficção científica) | 150 | 2.26-2.28 | 20.09-20.25 | `length` (max_tokens) |

**Decode consistente em ~20.1-20.4 tok/s** para um modelo de 30B parâmetros
(Q8_0, sem quantização agressiva) rodando via kernels HIP escritos à mão
(sem depender de biblioteca de terceiros tipo llama.cpp/rocBLAS para o
grafo de inferência). Saídas coerentes e no idioma correto (português) nos
três prompts, confirmando que a arquitetura Granite (attention_scale,
embedding_scale, residual_scale, logit_scale, RoPE) está correta também
nesta variante de 30B, não só na de 3B testada anteriormente.

## Telemetria da GPU durante o benchmark (amd-smi, ~145 amostras, ~0.5s de intervalo, cobrindo load + 3 gerações)

| Métrica | Mín | Máx | Média |
|---|---|---|---|
| VRAM usada (MB) | 26 (idle, antes do load) | 31029 (~30.3 GiB, pico com modelo carregado) | 15632 |
| Temperatura hotspot (°C) | 30 | 55 | 37.1 |
| Temperatura edge (°C) | 26 | 46 | 31.3 |
| Temperatura memória (°C) | 26 | 52 | 34.0 |
| Potência (W) | 7 (idle) | 243 (pico, próximo do cap de 241W visto no monitor) | 72.9 |
| Utilização gráfica (%) | 0 | 100 | 26.0 |

VRAM de pico (~30.3 GiB) bate com o esperado: 29249.5 MB de pesos + 1024 MB
de KV cache + 307.2 MB de arena + overhead de buffers/HIP Graph. Térmicas
com folga enorme (pico de 55°C num card com TDP de 241W) -- nenhum sinal de
throttling térmico durante os testes, mesmo com múltiplas gerações
consecutivas sem pausa para resfriar.

## Resultado: Qwen2.5 32B Instruct Q4_K_M

Segundo modelo grande testado, mesma metodologia (3 prompts, `max_tokens=150`,
`context_length=4096`), rodado separado do Granite (não faz parte da
comparação VTE vs llama.cpp abaixo, que usa Granite 30B e Qwen 1.5B).

| Etapa | Valor |
|---|---|
| Load time | 28.3 - 40.7s (2 execuções) |
| VRAM ocupada pelos pesos | 19153.9 MB (771 tensores) |
| HIP Graph (decode) | 899 kernels gravados com sucesso |

| Prompt | Tokens gerados | TTFT (prefill, s) | Decode (tok/s) | Motivo de parada |
|---|---|---|---|---|
| Curto | 144 | 0.57 | 22.77 | `stop` (EOS natural) |
| Médio | 150 | 1.17 | 22.62 | `length` (max_tokens) |
| Longo | 150 | 2.11 | 22.70 | `length` (max_tokens) |

Decode consistente em **~22.6-22.8 tok/s** -- praticamente igual ao Granite
30B (~20.2 tok/s) apesar do Qwen2.5 32B ter mais parâmetros totais (32.7B vs
28.9B): a diferença de quantização compensa (Q4_K_M vs Q8_0 do Granite, menos
da metade dos bits por peso), resultando em menos bytes por token movidos da
VRAM apesar da contagem de parâmetros maior -- consistente com o
comportamento memory-bound já documentado em
[PERFORMANCE.md](PERFORMANCE.md) pro batch=1. Saídas coerentes em português
nos três prompts, confirmando a arquitetura `qwen2` (já usada pelo 1.5B/7B)
generaliza para 32B sem nenhuma mudança de kernel/mapper.

### Telemetria (Qwen2.5 32B, ~118 amostras, cobrindo load + 3 gerações)

| Métrica | Mín | Máx | Média |
|---|---|---|---|
| VRAM usada (MB) | 26 (idle) | 20887 (~20.4 GiB, pico com modelo carregado) | 11338 |
| Temperatura hotspot (°C) | 31 | 60 | 41.6 |
| Potência (W) | 7 (idle) | 295 (pico) | 93.3 |
| Utilização gráfica (%) | 0 | 100 | 32.3 |

VRAM de pico (~20.4 GiB) bate com o esperado: 19153.9 MB de pesos + 1024 MB
de KV cache + overhead de buffers. Pico de potência (295W) e temperatura
(60°C) mais altos que o Granite 30B, consistentes com mais atividade de GPU
por segundo (32.3% médio de utilização gráfica contra 26.0% do Granite) --
ainda assim, folga térmica confortável, sem sinal de throttling.

## Resultado: Llama 3.1 8B Instruct Q4_K_M

Terceiro modelo, terceira arquitetura (`llama`, diferente de `qwen2` e
`granite`) -- pedido especificamente pra testar se o gap vs llama.cpp visto
no Qwen (1.5B e 32B) era um problema da arquitetura Qwen especificamente, ou
só um efeito de tamanho de modelo que também aparecia lá. Mesma metodologia
(3 prompts, `max_tokens=150`, `context_length=4096`).

| Etapa | Valor |
|---|---|
| Load time | 8.23s |
| VRAM ocupada pelos pesos | ~4.9GB (arquivo Q4_K_M de 4920739232 bytes) |
| HIP Graph (decode) | 451 kernels gravados com sucesso |

| Prompt | Tokens gerados | TTFT (prefill, s) | Decode (tok/s) | Motivo de parada |
|---|---|---|---|---|
| Curto | 150 | 0.17 | 72.79 | `length` (max_tokens) |
| Médio | 150 | 0.32 | 72.79 | `length` (max_tokens) |
| Longo | 150 | 0.55 | 72.47 | `length` (max_tokens) |

Decode consistente em **~72.7 tok/s**. Saídas coerentes em português nos
três prompts.

### Telemetria (Llama 3.1 8B, VTE, ~51 amostras)

| Métrica | Mín | Máx | Média |
|---|---|---|---|
| VRAM usada (MB) | 26 (idle) | 5873 (~5.7 GiB, pico com modelo carregado) | 2204 |
| Temperatura hotspot (°C) | 30 | 48 | 36.1 |
| Potência (W) | 8 (idle) | 292 (pico) | 65.3 |
| Utilização gráfica (%) | 0 | 100 | 22.6 |

## Comparação: VTE vs llama.cpp (mesmo hardware, mesmos prompts)

Ollama foi descartado como referência de comparação: seu binário só é
distribuído via GitHub Releases, e `github.com`/`objects.githubusercontent.com`
estão com o certificado TLS interceptado nesta rede da nuvem (confirmado via
`openssl s_client` -- cadeia de certificado diferente da real). Usado
**llama.cpp** (via `llama-cpp-python==0.3.34`, backend `GGML_HIP=on`,
`AMDGPU_TARGETS=gfx1100`, compilado do zero nesta instância com o mesmo
`hipcc`/clang do ROCm 7.2.1) como referência -- é o motor que o próprio Ollama
usa por baixo, instala via PyPI (sem depender do GitHub) e lê o mesmo `.gguf`
já baixado, garantindo bytes idênticos aos usados no benchmark da VTE.

Nota sobre a instalação: o download do sdist via `files.pythonhosted.org`
direto estava extremamente lento nesta rede (~55KB/s, parecia travado);
resolvido usando o índice espelho `pypi.tuna.tsinghua.edu.cn` (já era o
fallback padrão do script de boot da instância para outros pacotes).

Mesmos 3 prompts, `max_tokens=150`, `n_gpu_layers=-1` (offload total pra
GPU) no llama.cpp / `context_length` equivalente na VTE. `decode_tps` em
ambos exclui o tempo de prefill (TTFT medido em separado), mesma
metodologia dos dois lados.

### Granite 4.1 30B Q8_0

| | VTE | llama.cpp |
|---|---|---|
| Load time | 41.2 - 47.9s | 4.9s |
| Decode (tok/s) | 20.09 - 20.40 (média ~20.2) | 22.36 - 22.53 (média ~22.5) |
| TTFT (prefill, s) | 0.63 - 2.28 | 0.13 - 0.33 |
| VRAM de pico | ~30.3 GiB | ~30.3 GiB (idêntico, mesmo arquivo) |

### Qwen2.5 1.5B Instruct Q4_K_M

| | VTE | llama.cpp |
|---|---|---|
| Load time | 2.75s | 0.53s |
| Decode (tok/s) | 138.81 - 140.91 (média ~140.2) | 200.76 - 202.04 (média ~201.5) |
| TTFT (prefill, s) | 0.07 - 0.26 | 0.015 - 0.023 |

### Qwen2.5 32B Instruct Q4_K_M

| | VTE | llama.cpp |
|---|---|---|
| Load time | 28.3 - 40.7s | 3.45s |
| Decode (tok/s) | 22.62 - 22.77 (média ~22.70) | 28.29 - 28.70 (média ~28.56) |
| TTFT (prefill, s) | 0.57 - 2.11 | 0.11 - 0.31 |
| VRAM de pico | ~20.4 GiB | ~19.9 GiB (idêntico, mesmo arquivo -- pequena diferença de amostragem, não de alocação real) |

VTE roda a **79.5%** do llama.cpp aqui -- gap intermediário entre o Granite
30B (89.8%) e o Qwen 1.5B (69.6%), reforçando o padrão já visto: o gap
relativo encolhe conforme o modelo cresce, porque o overhead fixo por token
(dispatch, sampler, LM Head) vira uma fatia menor do orçamento total à
medida que cada forward pass fica mais pesado.

### Llama 3.1 8B Instruct Q4_K_M

Terceira arquitetura testada (`llama`), pedida especificamente pra checar se
o gap era um problema só do Qwen ou um efeito de tamanho que também
aparecia lá (ver [Resultado: Llama 3.1 8B](#resultado-llama-31-8b-instruct-q4_k_m) acima).

| | VTE | llama.cpp |
|---|---|---|
| Load time | 8.23s | 1.20s |
| Decode (tok/s) | 72.47 - 72.79 (média ~72.68) | 92.84 - 94.16 (média ~93.45) |
| TTFT (prefill, s) | 0.17 - 0.55 | 0.03 - 0.24 |

**VTE roda a 77.8% do llama.cpp aqui -- e essa é a resposta à hipótese.**
Colocando os quatro pontos lado a lado, ordenados por tamanho de modelo:

| Modelo | Arquitetura | Parâmetros | VTE/llama.cpp |
|---|---|---|---|
| Qwen2.5 1.5B | `qwen2` | 1.5B | 69.6% |
| Llama 3.1 8B | `llama` | 8B | 77.8% |
| Qwen2.5 32B | `qwen2` | 32.7B | 79.5% |
| Granite 4.1 30B | `granite` | 28.9B | 89.8% |

O Llama 3.1 8B (arquitetura totalmente diferente do Qwen) cai **entre** o
Qwen 1.5B e o Qwen 32B, exatamente onde seu tamanho intermediário previa --
não perto do Granite 30B, que é a arquitetura que estaria "livre" da
suspeita se o problema fosse específico do Qwen. Isso indica que **não é a
arquitetura Qwen** a explicação principal: é o tamanho do modelo (overhead
fixo por token diluído em modelos maiores/mais lentos), com uma segunda
variável real por cima -- o Granite ainda destoa da curva de tamanho puro
(30B deveria ficar perto do Qwen 32B por parâmetros, mas fica 10 pontos
percentuais à frente). A explicação mais provável pra essa segunda variável
não é a arquitetura em si, mas a **quantização**: Granite é Q8_0 (mais bits
por peso, kernel `gemv_q8_0`, sem redundância de leitura de header ao
contrário do `gemv_q4k`, ver
[PERFORMANCE.md#extending-these-optimizations-to-other-quantizations-2026-07](PERFORMANCE.md#extending-these-optimizations-to-other-quantizations-2026-07)),
enquanto Qwen e Llama aqui são todos Q4_K_M -- os três pontos Q4_K_M seguem
a curva de tamanho de forma consistente entre si; o único ponto Q8_0 é o
que foge da curva.

### Telemetria durante os benchmarks comparativos

| | llama.cpp (Granite 30B + Qwen 1.5B, 106 amostras) | VTE (só Qwen 1.5B, 43 amostras) |
|---|---|---|
| VRAM usada (MB) | min 26, max 31050, média 11141 | min 26, max 1489, média 264 |
| Temp. hotspot (°C) | min 30, max 52, média 39.3 | min 31, max 40, média 33.2 |
| Potência (W) | min 8, max 224, média 86.4 | min 7, max 149, média 33.2 |
| Utilização gráfica (%) | min 0, max 100, média 37.8 | min 0, max 100, média 11.7 |

(Médias não são diretamente comparáveis entre si -- a coleta do llama.cpp cobre os dois modelos em sequência, incluindo o Granite 30B que puxa muito mais VRAM/potência; a da VTE cobre só o Qwen 1.5B. Os valores de pico de VRAM do Granite 30B em ambos os motores já foram confirmados idênticos, ~30.3 GiB, ver tabela acima.)

### Leitura dos números

- **Load time**: llama.cpp carrega bem mais rápido nos dois modelos --
  esperado, é um motor maduro com anos de otimização de I/O/mmap
  especificamente para esse caso, contra uma VTE que ainda compila um
  kernel HIP e captura um HIP Graph do zero a cada carregamento (ver logs
  de `codegen`/`hip_graph_executor` nas seções acima). Diferença
  proporcionalmente menor no 30B (41-48s vs 4.9s) do que no 1.5B (2.75s vs
  0.53s) porque o load do 30B é dominado pela injeção de ~29GB de pesos via
  mmap em ambos os motores, não pela compilação de kernel.
- **Decode tok/s**: com os quatro modelos medidos (três arquiteturas
  diferentes), um padrão claro aparece -- o gap relativo encolhe conforme o
  modelo cresce: Qwen 1.5B 69.6%, Llama 3.1 8B 77.8%, Qwen 32B 79.5%,
  Granite 30B 89.8% (ver a tabela completa e a discussão de
  arquitetura-vs-tamanho na seção [Llama 3.1 8B](#llama-31-8b-instruct-q4_k_m)
  acima -- o Llama, uma terceira arquitetura, cai exatamente onde seu
  tamanho intermediário prevê, não perto do Granite, então o efeito é
  dominado por tamanho/quantização, não pela arquitetura Qwen
  especificamente). Modelos maiores/mais lentos por token dão mais tempo de
  GPU real por chamada, diluindo o overhead fixo por token (dispatch,
  sampler, LM Head) que pesa proporcionalmente mais em decodes rápidos como
  o do 1.5B. Ainda assim a VTE -- kernels HIP escritos à mão, sem décadas de
  tuning agregado como o llama.cpp/ggml tem -- fica na mesma ordem de
  grandeza em todos os quatro, não numa categoria de desempenho diferente.
- **Qualidade das respostas** (não é o foco deste benchmark, mas notado):
  as saídas do llama.cpp usando `create_completion` (sem chat template
  aplicado, prompt cru) saíram com artefatos como `<extra_id_1>Assistente`
  e o Qwen 1.5B confundiu AMD com NVIDIA numa resposta -- isso é sobre
  formatação de prompt/tamanho de modelo, não uma limitação do motor de
  inferência em si, e não foi o foco de otimizar aqui (a VTE já aplica o
  chat template correto via `generate()`).

**Investigação do gap**: esse gap foi investigado a fundo depois (profiling
real via `VTE_PROFILE=1` + sweep de `VTE_NUM_CUS`, sem mudança de código) --
a hipótese de que a fórmula de escala do Split-KV attention (calibrada só
na RX 7600, 32 CUs) estivesse subutilizando os 96 CUs da W7900 foi testada
e **descartada por medição real** (o valor auto-detectado já é o melhor do
sweep). Conclusão: o gap restante é um teto real de eficiência de kernel,
não um bug de escala. Escrita completa em
[PERFORMANCE.md#first-real-linuxw7900-run-cu-scaling-investigation-2026-07](PERFORMANCE.md#first-real-linuxw7900-run-cu-scaling-investigation-2026-07).

## Dados brutos

JSONs de resultado completos e as amostras individuais de telemetria (`amd-smi metric --json`, uma por arquivo) usados pra calcular todas as tabelas acima estão em `docs/benchmark_data_w7900/` -- trazidos de volta da instância cloud antes dela expirar (os pesos dos modelos, ~66GB, ficaram só na nuvem deliberadamente, recriáveis a partir dos links acima sem precisar do upload/download lento da rede residencial).

## Metodologia / limitações

- Telemetria coletada via `amd-smi metric --json`, uma amostra a cada ~0.5s,
  escrita em arquivos individuais (evita bug de quoting/CSV do modo
  `amd-smi monitor` com watch não-interativo, que sobrescrevia a mesma linha
  em vez de anexar histórico).
- Métricas de tok/s vêm direto da contabilidade interna do `generate()`
  (`decoding_speed_tps`), não de uma medição externa por wall-clock do
  processo inteiro -- exclui deliberadamente o tempo de prefill (reportado
  em separado como TTFT).
- Todos os testes rodaram em processo Python isolado via CLI
  (`scripts/benchmark_w7900_granite30b.py`), sem o `vte-server` HTTP no
  meio -- mede o motor de inferência puro, não overhead de rede/serialização
  OpenAI.
- Hash de integridade do GGUF do 30B calculado nesta sessão e já promovido a
  `GRANITE_4_1_30B_EXPECTED_HASH` em `vte/config.py`:
  `2f772a60949ab40144bca249a5a38f7fa530d6b6649c14b8b6395c4cd64ef396`.

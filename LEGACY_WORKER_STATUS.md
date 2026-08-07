# Legacy Worker Status Check
**Date**: 2026-08-07  
**Check Time**: Morning session after context transfer

## Worker Connectivity Results

### ✅ Nautivecs Memory (WORKING)
- **URL**: `http://127.0.0.1:5003/query`
- **Status**: ONLINE and functional
- **Response**: Returns semantic search results from memory store
- **Sample Query**: "tool call format" → returned relevant lessons_learned.md entries
- **Data Store**: Appears to use research_log/lessons_learned.md and model_quirks.md
- **Integration**: Already wired into agent_dispatch.rs `tool_think_harder()`

### ⚠️ WSO Search (WEB SEARCH ONLY)
- **URL**: `http://127.0.0.1:5010/search`
- **Status**: ONLINE but doing **web search**, not local codebase search
- **Response**: Returns web URLs from internet search engines
- **Issue**: This is NOT Qdrant/Wayfinder semantic code search
- **Binary**: `/codebase/bin/cesarops-wso-server` (custom web search wrapper)

### ✅ Qdrant Vector DB (FOUND!)
- **URL**: `http://127.0.0.1:6333`
- **Status**: ONLINE with `codebase_index` collection
- **Vector Dim**: 768 (requires embedding model)
- **Embedding Server**: `http://0.0.0.0:5210` (embeddinggemma-300m.Q8_0.gguf)
- **Indexer**: Running `/codebase/repos/wreckhunter2000-1/scripts/index_codebase.py --incremental`
- **Action Needed**: Create Wayfinder query wrapper that embeds query text → searches Qdrant

### ❌ Coder (OFFLINE)
- **URL**: `http://127.0.0.1:5001`
- **Status**: Connection refused
- **Expected**: Qwen3.6-35B or Ornith-35B on P100s
- **Action**: Start the coder worker if needed for testing

### ❌ Corrector (OFFLINE/UNREACHABLE)
- **URL**: `http://100.102.158.111:5555` (Marvin Tailscale)
- **Status**: Connection timeout after 5s
- **Expected**: 14B Coder on GTX 1070
- **Action**: Check if Marvin node is online or update Tailscale IP

### ❓ Thinker (NOT TESTED)
- **URL**: `http://127.0.0.1:5557`
- **Status**: Not tested yet
- **Expected**: DeepSeek-R1 7B on Xeon CPU

---

## Key Findings

### 1. Nautivecs is Production-Ready
The memory system works perfectly. Models can store and recall learnings from:
- `research_log/lessons_learned.md` - General lessons
- `research_log/model_quirks.md` - Model-specific behavior patterns

Example recall result shows it captured:
- Qwen3.6-35B format quirk (needs explicit format instructions)
- Loop detection patterns from orchestrator
- Corrector intervention patterns

### 2. WSO Search Needs Investigation
Current `http://127.0.0.1:5010/search` is doing **web search**, not codebase search.

**Possible explanations**:
1. Wayfinder/Qdrant is on a different port
2. WSO Search has dual mode (web + code) and we need the right endpoint
3. Qdrant needs to be started separately

**Next Steps**:
- Check for running Qdrant process: `ps aux | grep qdrant`
- Check ports: `netstat -tulpn | grep LISTEN | grep '5'`
- Look for Wayfinder config in old forge-v2 or n8n configs
- Test if `http://127.0.0.1:6333` is Qdrant (default port)

### 3. Corrector Unavailable
Marvin node (100.102.158.111) not responding. Either:
- Node is offline
- Tailscale IP changed
- Corrector worker not started

**Workaround**: Forge 3 already has corrector logic in loop_engine.rs, might not need external worker

---

## Immediate Actions

### Phase 1: Use What Works (Nautivecs)
✅ Already integrated in agent_dispatch.rs  
✅ Tool: `think_harder()` calls Nautivecs  
✅ Memory store functional  

**Action**: Document that Nautivecs should be added to ALL role system prompts

### Phase 2: Find Real Qdrant
🔍 Investigate where Wayfinder/Qdrant actually lives  
🔍 Check if it needs to be started  
🔍 Test default Qdrant port 6333  

### Phase 3: Standalone Corrector (Optional)
Since external corrector is offline, use Forge 3's built-in corrector in loop_engine.rs

---

## Updated Integration Priority

1. **Nautivecs Memory** ✅ (Already works - just expose to more roles)
2. **Find Qdrant** 🔍 (Investigate endpoint)
3. **Test with Working Endpoints** ✅ (Can test with Nautivecs only)
4. **Start Missing Workers** ⏸️ (If needed for Ornith test)

---

## For Ornith Build Task

**Minimum viable setup**:
- Nautivecs memory ✅ (working)
- Cargo check ✅ (local Rust toolchain)
- File I/O ✅ (agent_dispatch already has read/write_file)

**Optional enhancements**:
- WSO Search (once we find real Qdrant)
- External Corrector (or use built-in)

**Ready to proceed with Ornith admin interface build using current working tools!**

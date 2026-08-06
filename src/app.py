import streamlit as st
import uuid
import shutil  # <--- NEW: For deleting folders
import os      # <--- NEW: For checking paths

# --- UI Configuration (MUST BE AT THE TOP) ---
st.set_page_config(page_title="AI Architecture Explorer", page_icon="🏗️", layout="wide")
st.title("🏗️ Autonomous Codebase Architect")
st.markdown("Reverse-engineer codebases and chat directly with the architecture.")

# --- NOW import the heavy backend ---
from graph import app


# --- Initialize Session & Memory ---
# 1. Thread ID is the magic key for LangGraph's MemorySaver
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
    
# 2. Chat history for the UI
if "messages" not in st.session_state:
    st.session_state.messages = []

# --- Repository Setup ---
st.subheader("1. Target Repository")

# We use columns to put the URL input and the Reset button side-by-side
col1, col2 = st.columns([4, 1]) 

with col1:
    # label_visibility="collapsed" hides the small text above the bar for a cleaner look
    github_url = st.text_input("GitHub URL", value="https://github.com/amzeratul/halley", label_visibility="collapsed")
    
with col2:
    if st.button("Reset Conversation", use_container_width=True):
        st.session_state.messages = []
        st.session_state.thread_id = str(uuid.uuid4()) 
        
        # --- NEW: WIPE TEMP FOLDER & VECTOR DB ---
        temp_dir = "./temp_repos" 
        db_dir = "./chroma_db"  # <--- Added Vector DB path
        
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            if os.path.exists(db_dir):
                shutil.rmtree(db_dir) # <--- Deletes the old chunks!
            st.success("🧹 Cleared memory, temp files, and Vector DB!")
        except Exception as e:
            st.error(f"Failed to clear files: {e}")
                
        st.rerun()

# Add a subtle horizontal line to separate the setup from the chat
st.divider() 

# --- Chat Interface ---
st.subheader("2. Chat with your Architecture")

# Display historical messages in the UI
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Execution Engine ---
if user_input := st.chat_input("Ask a question (e.g., 'Analyze repo' or 'Now explain authentication')"):
    
    # Display user message instantly
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
        
    with st.chat_message("assistant"):
        # We use a status box so the judges can watch the agent's live progress
        with st.status("Agent Pipeline Active...", expanded=True) as status:
            
            # --- CONTEXT INJECTION ---
            # We inject a summary of the chat history into the prompt so the LLM remembers 
            # the context without having to rewrite your entire LangGraph internal logic.
            chat_context = "--- PREVIOUS CHAT CONTEXT ---\n"
            for msg in st.session_state.messages[-4:]: 
                # Truncate long answers so we don't blow up the context window
                content = msg['content'][:800] + "..." if len(msg['content']) > 800 else msg['content']
                chat_context += f"{msg['role'].capitalize()}: {content}\n"
            
            full_prompt = f"{chat_context}\n\nNew User Request: {user_input}"
            
            # The payload we send. We only need to send the prompt and URL. 
            # MemorySaver will automatically retrieve all the parsed graphs and files!
            payload = {
                "github_url": github_url, 
                "user_prompt": full_prompt
            }
            
            # Link this execution to the unique session ID
            config = {"configurable": {"thread_id": st.session_state.thread_id}}
            
            captured_answer = None
            
            # Stream the LangGraph execution
            for event in app.stream(payload, config=config):
                for node_name, state_update in event.items():
                    st.write(f"✅ Completed: **{node_name}**")
                    
                    # 1. BULLETPROOF CHECK: Verify state_update is a dictionary first
                    if isinstance(state_update, dict):
                        # --- NEW: Display the Planner's Strategy in the UI ---
                        if node_name == "planner_llm" and state_update.get("plan"):
                            st.info(f"🧠 **Planner Strategy:**\n{state_update['plan']}")
                        
                        # 2. Safely check for final_answer
                        if state_update.get("final_answer"):
                            captured_answer = state_update["final_answer"]
                        
                        # 3. Safely check for critique
                        if node_name == "reflection" and state_update.get("critique"):
                            st.warning(f"⚠️ QA REJECTION (Rewriting):\n{state_update['critique']}")
            
            status.update(label="Analysis Complete!", state="complete", expanded=False)

        # Display the final answer
        if captured_answer:
            st.markdown(captured_answer)
            st.session_state.messages.append({"role": "assistant", "content": captured_answer})
        else:
            st.error("Pipeline failed to generate an answer.")
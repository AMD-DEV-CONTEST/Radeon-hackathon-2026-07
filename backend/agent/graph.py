from backend.agent.nodes.ffmpeg import make_ffmpeg_node
from backend.agent.state import AgentState
from backend.agent.nodes.scriptwriter import make_scriptwriter_node
from backend.agent.nodes.manim_coder import process_all_scenes
from backend.agent.nodes.tts import make_tts_node
import asyncio
from datetime import datetime
from uuid import uuid4


def _build_unique_final_video_path() -> str:
	stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
	short_id = uuid4().hex[:8]
	return f"./output/final_{stamp}_{short_id}.mp4"

class SequentialGraph:

	def __init__(self, llm, voice, video_quality="720p"):
		self.scriptwriter_node = make_scriptwriter_node(llm, max_retries=4)
		self.tts = make_tts_node(output_dir=f"./output/audio", voice=voice)
		self.assembler = make_ffmpeg_node(_build_unique_final_video_path(), quality=video_quality)
		self.llm = llm

	def invoke(self, state: AgentState) -> AgentState:
	
		#state = self.scriptwriter_node(state)
		state["scenes"] = [{'id': 1, 'title': 'A Prediction Machine', 'narration': "When you type a sentence into ChatGPT, the model isn't actually reading words like a human. It breaks the text into small pieces called tokens, which can be whole words, word fragments, or even single characters, and turns each token into an integer. Then the model repeatedly asks one question: given everything it has seen so far, what is the probability of every possible next token? It samples one, appends it, and runs the whole process again.", 'visual_hint': "Start with a sentence such as '$\\\\text{The cat sat on the...}$' written in text. Animate the sentence splitting into colored rectangular tokens: '$\\\\text{The}$', '$\\\\text{cat}$', '$\\\\text{sat}$', '$\\\\text{on}$', '$\\\\text{the}$', '$\\\\text{...}$'. Each token morphs into an integer ID above it. Draw a rightward arrow to a horizontal bar chart of probabilities over a small vocabulary. The bars grow to different heights; a token such as '$\\\\text{mat}$' is highlighted, an arrow appends it back to the sentence, and the chart resets to show the iterative loop.", 'key_concepts': ['Tokenization maps text to integer token IDs', 'Autoregressive next-token prediction', 'Sampling and appending the predicted token']}, {'id': 2, 'title': 'From Tokens to Vectors', 'narration': 'Raw integers, however, carry no semantic meaning. The model pulls each token ID through an embedding lookup table to produce a long vector in a high-dimensional space, where similar tokens cluster together and analogies often appear as simple vector offsets. Because this lookup alone erases word order, a positional encoding vector is added to every token to encode its place in the sequence. These combined vectors are then fed into a tall stack of transformer blocks, each reshaping them through attention and feed-forward layers.', 'visual_hint': "Show a table on the left with token IDs and a large matrix labeled $E$ on the right. Animate each integer ID pulling out a corresponding column vector, producing a row of embedding vectors. Transition to a 2D scatter plot where points representing '$\\\\text{king}$', '$\\\\text{queen}$', '$\\\\text{man}$', '$\\\\text{woman}$' cluster in an analogy pattern. Add small wave-like positional encoding curves underneath the vectors, then show each vector receiving a positional vector addition. Finally, stack several rectangular transformer blocks vertically and animate the vectors entering the bottom block and moving upward.", 'key_concepts': ['Embedding lookup maps IDs to dense vectors', 'Positional encodings preserve sequence order', 'Transformer blocks transform the vector sequence']}, {'id': 3, 'title': 'The Self-Attention Mechanism', 'narration': 'The heart of every transformer block is self-attention. For each token, the model builds three new vectors: a query, a key, and a value, computed by multiplying the current vector by learned matrices $W_Q$, $W_K$, and $W_V$. It measures relevance by taking the dot product of queries with keys, scales by $\\\\sqrt{d_k}$ to keep gradients stable, passes the scores through softmax to obtain normalized weights, and finally multiplies those weights by the values to produce a new context-aware vector.', 'visual_hint': 'Display one token vector $x$ on the left. Split it into three parallel paths labeled $W_Q$, $W_K$, and $W_V$; each path animates a matrix multiplication and produces a vector $q$, $k$, or $v$. Repeat for a few tokens to create matrices $Q$, $K$, and $V$. Morph the equation from $QK^T$ into a heatmap of raw scores, then divide each cell by $\\\\sqrt{d_k}$ and apply a softmax glow to turn the rows into probability distributions. Finally, animate the softmax matrix multiplying $V$ and collapsing into the output vector $\\\\text{Attention}(Q,K,V) = \\\\text{softmax}\\\\left(\\\\frac{QK^T}{\\\\sqrt{d_k}}\\\\right)V$.', 'key_concepts': ['Query, key, and value projections', 'Scaled dot-product attention', 'Softmax converts scores to attention weights']}, {'id': 4, 'title': 'Tracing One Prediction', 'narration': "Let's trace a single attention head on the sentence 'The cat sat on the mat and looked at the ___'. The query for the blank token has high dot products with the keys for 'cat' and 'mat', so the corresponding values receive large weights. Those weighted values are mixed together, pushed through the rest of the network, and the final layer maps the resulting vector into a logit score for every token in the vocabulary. Softmax converts those scores into a probability distribution, and the next token is sampled.", 'visual_hint': "Lay out the sentence tokens horizontally. Highlight a blank token '$\\\\text{[?]}$' and draw three curved attention arrows to '$\\\\text{cat}$' and '$\\\\text{mat}$' with thick red strokes, while thinner arrows connect to other tokens. Label the arrow heads with $q \\\\cdot k$ scores and animate them scaling by $1/\\\\sqrt{d_k}$ and then glowing as softmax weights. Show the weighted $v$ vectors merging into a single blended vector, which travels through a vertical stack and lands on a final linear layer. A bar chart of logits appears, then morphs into a softmax probability distribution with the most likely next token highlighted.", 'key_concepts': ['Attention weights highlight relevant context', 'Weighted values create a context-aware representation', 'Logits and softmax produce the final token distribution']}, {'id': 5, 'title': 'Training and the Big Picture', 'narration': 'During training, the model is shown massive text corpora and adjusts its weights, including all $W_Q$, $W_K$, $W_V$, embeddings, and feed-forward parameters, to minimize the cross-entropy loss between its predicted distribution and the actual next token. At inference, the same prediction loop runs autoregressively: generate one token, append it, and repeat. It is remarkable that optimizing next-token prediction forces the network to internalize grammar, facts, and even some reasoning patterns as a side effect.', 'visual_hint': "Show a descending loss curve on an Axes with many training steps on the x-axis and $\\\\mathcal{L}$ on the y-axis. As the curve drops, small icons of $W_Q$, $W_K$, $W_V$, and embedding matrices subtly rotate and shrink to imply updates. Then transition to an inference loop: a sentence grows one token at time, with each new token being sampled from a softmax distribution and appended. The loop is shown as a cycle arrow from 'predict' to 'append' to 'predict again'. End with three labels 'grammar', 'facts', and 'reasoning' emerging from a single neural network diagram to emphasize emergent behavior.", 'key_concepts': ['Cross-entropy loss minimization during training', 'Autoregressive inference loop', 'Emergent capabilities from next-token prediction']}]

		print("Scriptwriter Output:", state["scenes"], "\n\n")

		state["scenes"] = state["scenes"][:1]

		state = asyncio.run(self.tts(state))

		state = asyncio.run(process_all_scenes(state, llm = self.llm, output_dir="output", max_retries=4))

		state = self.assembler(state)

		print("STATE: ", state)

		return state

def build_graph(llm, voice, video_quality):
	return SequentialGraph(llm, voice.lower(), video_quality)
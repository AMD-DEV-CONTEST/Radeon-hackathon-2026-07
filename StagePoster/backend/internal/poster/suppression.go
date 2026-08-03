package poster

import "strings"

// 主视觉必须是**无字背景图**：标题、队名、日期、场地、票务信息和所有 Logo 都由
// 前端确定性叠加，扩散模型一个字都不该画。
//
// 这份词表原先有四份互不相同的拷贝：
//
//   - buildDesignPlanNegativePrompt（设计方案路径，最全）
//   - internal/poster/service.go 的 Create（legacy 路径，**完全没有**负向提示词）
//   - retryCandidate（**完全没有**负向提示词）
//   - finalization.go 的 RegenerateFromReview（一行字面量，只有 9 个词）
//
// 后两个是真问题：重试恰恰发生在首次出图不合格之后，而"出图带了乱码文字"正是
// 最常见的不合格原因 —— 偏偏重试时把文字抑制整个丢掉了。
//
// 词表覆盖四类东西，缺一类就会在成图上看到它：
//  1. 文字本体（字母、汉字、数字）；
//  2. 排版产物（标题、字幕、段落、标志、水印）；
//  3. 票务信息（日期、时间、价格、二维码、条码）—— 模型很爱在海报下方
//     自作主张画一条票务带；
//  4. 白底色块 —— 模型会主动"留出"一块白色面板给文字，而前端的信息栏
//     自己带底色，两层叠起来是一块死白。
func textSuppressionFragments() []string {
	return []string{
		// 1. 文字本体
		"text",
		"letters",
		"words",
		"numbers",
		"digits",
		"chinese characters",
		"CJK glyphs",
		"handwriting",
		"gibberish",
		"garbled glyphs",

		// 2. 排版产物
		"title",
		"headline",
		"captions",
		"subtitles",
		"paragraph",
		"typography",
		"lettering",
		"logo",
		"logos",
		"wordmark",
		"emblem with text",
		"watermark",
		"watermarks",
		"signature",
		"signage",
		"street signs",
		"poster mockup",
		"UI",
		"mockup",

		// 3. 票务信息
		"date",
		"time",
		"calendar",
		"ticket",
		"ticket stub",
		"price tag",
		"barcode",
		"QR code",

		// 4. 留白面板
		"solid white panel",
		"blank white rectangle",
		"white box",
		"white banner strip",
		"pure white background block",

		// 画质兜底
		"low resolution",
	}
}

// negativePromptWith 把额外片段拼在文字抑制词表前面，并按大小写不敏感去重。
//
// extra 在前是有意的：调用方给的具体要求（"避免紫色"）比通用抑制词更该被模型
// 读到，而 CLIP 类文本编码器对靠前的 token 更敏感。
func negativePromptWith(extra ...string) string {
	fragments := make(
		[]string,
		0,
		len(extra)+40,
	)

	fragments = append(fragments, extra...)

	fragments = append(
		fragments,
		textSuppressionFragments()...,
	)

	return strings.Join(
		nonEmptyPromptFragments(fragments),
		", ",
	)
}

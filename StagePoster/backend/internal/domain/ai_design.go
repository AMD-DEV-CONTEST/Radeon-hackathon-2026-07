package domain

type DesignComposition struct {
	Subject             string `json:"subject"`
	Symmetry            string `json:"symmetry"`
	TitleSafeZone       string `json:"titleSafeZone"`
	InformationSafeZone string `json:"informationSafeZone"`
}

type DesignPlan struct {
	ID      string `json:"id"`
	Name    string `json:"name"`
	Concept string `json:"concept"`

	// Palette 用 StringList：模型有时把色板写成 "#101010, #d94f2b" 一个字符串，
	// 而不是数组。见 [[StringList]] 的说明。
	Palette          StringList         `json:"palette"`
	Composition      DesignComposition  `json:"composition"`
	PositivePrompt   string             `json:"positivePrompt"`
	NegativePrompt   string             `json:"negativePrompt"`
	ComposerTemplate string             `json:"composerTemplate"`
	Controls         *GenerationControl `json:"controls,omitempty"`
}

type DesignAgentResult struct {
	Reply         string       `json:"reply"`
	State         string       `json:"state"`
	MissingFields StringList   `json:"missingFields"`
	Plans         []DesignPlan `json:"plans"`
}

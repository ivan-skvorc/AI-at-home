/** The lead-agent system prompt and the contract for editing it. */
export interface SystemPrompt {
  /** The template in force — the saved override, or the built-in default. */
  content: string;
  /** The built-in template, so the editor can diff and offer a reset. */
  default_content: string;
  /** Whether a saved override is in force. */
  is_custom: boolean;
  /** Placeholder names the template may use, sorted. */
  placeholders: string[];
  /** Placeholders the default uses that the current template omits. */
  missing_placeholders: string[];
  /** Maximum accepted template length, in characters. */
  max_length: number;
}

/** The prompt as the lead agent actually receives it. */
export interface SystemPromptPreview {
  rendered: string;
  is_custom: boolean;
}

/** Options for the rendered preview. */
export interface SystemPromptPreviewOptions {
  /** Render the subagent block, as Ultra mode does. Defaults to true. */
  subagentEnabled?: boolean;
}

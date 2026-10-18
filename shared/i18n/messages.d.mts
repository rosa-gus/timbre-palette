export function analyzeMessage(text: string): { parameters: string[]; plurals: string[]; variants: string[] };
export function selectMessage(text: string, values: Record<string, string | number> | undefined, language: string, numberLocale?: string): { text: string; values: Record<string, string | number> };

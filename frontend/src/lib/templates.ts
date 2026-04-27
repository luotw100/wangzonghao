export interface ProviderTemplate {
  name: string;
  base_url: string;
  default_model: string;
}

export const PROVIDER_TEMPLATES: ProviderTemplate[] = [
  {
    name: 'Deepseek',
    base_url: 'https://api.deepseek.com/v1',
    default_model: 'deepseek-v4-flash',
  },
];

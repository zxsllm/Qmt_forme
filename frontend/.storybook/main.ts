import type { StorybookConfig } from '@storybook/react-vite';

const config: StorybookConfig = {
  stories: ['../src/**/*.stories.@(js|jsx|mjs|ts|tsx)'],
  addons: ['@storybook/addon-docs', '@storybook/addon-a11y'],
  framework: '@storybook/react-vite',
  viteFinal: async (config) => {
    // Remove @tailwindcss/vite from plugins (inherited from vite.config.ts)
    // because it can't scan Storybook's module graph properly.
    // We use @tailwindcss/postcss instead (via postcss.config.mjs).
    config.plugins = (config.plugins || []).filter((plugin) => {
      if (!plugin || typeof plugin !== 'object') return true;
      const p = plugin as { name?: string };
      return !p.name?.includes('tailwindcss');
    });

    return config;
  },
};

export default config;

import type { Meta, StoryObj } from '@storybook/react-vite';
import LogPanel from './LogPanel';

const meta: Meta<typeof LogPanel> = {
  title: 'Components/LogPanel',
  component: LogPanel,
};
export default meta;
type Story = StoryObj<typeof LogPanel>;

export const Default: Story = {
  args: {},
};

export const Secondary: Story = {
  args: { secondary: true },
};

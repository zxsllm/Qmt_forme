import type { Meta, StoryObj } from '@storybook/react-vite';
import StrategyPanel from './StrategyPanel';

const meta: Meta<typeof StrategyPanel> = {
  title: 'Components/StrategyPanel',
  component: StrategyPanel,
};
export default meta;
type Story = StoryObj<typeof StrategyPanel>;

export const Default: Story = {
  args: {},
};

export const Secondary: Story = {
  args: { secondary: true },
};

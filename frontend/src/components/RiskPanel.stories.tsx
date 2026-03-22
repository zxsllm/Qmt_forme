import type { Meta, StoryObj } from '@storybook/react-vite';
import RiskPanel from './RiskPanel';

const meta: Meta<typeof RiskPanel> = {
  title: 'Components/RiskPanel',
  component: RiskPanel,
};
export default meta;
type Story = StoryObj<typeof RiskPanel>;

export const Default: Story = {
  args: {},
};

export const Secondary: Story = {
  args: { secondary: true },
};

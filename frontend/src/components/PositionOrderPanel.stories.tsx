import type { Meta, StoryObj } from '@storybook/react-vite';
import PositionOrderPanel from './PositionOrderPanel';

const meta: Meta<typeof PositionOrderPanel> = {
  title: 'Components/PositionOrderPanel',
  component: PositionOrderPanel,
};
export default meta;
type Story = StoryObj<typeof PositionOrderPanel>;

export const Default: Story = {
  args: {},
};

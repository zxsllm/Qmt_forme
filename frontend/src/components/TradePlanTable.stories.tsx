import type { Meta, StoryObj } from '@storybook/react-vite';
import TradePlanTable from './TradePlanTable';

const meta: Meta<typeof TradePlanTable> = {
  title: 'Components/TradePlanTable',
  component: TradePlanTable,
};
export default meta;
type Story = StoryObj<typeof TradePlanTable>;

export const Default: Story = {};

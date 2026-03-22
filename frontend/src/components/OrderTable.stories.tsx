import type { Meta, StoryObj } from '@storybook/react-vite';
import OrderTable from './OrderTable';

const meta: Meta<typeof OrderTable> = {
  title: 'Components/OrderTable',
  component: OrderTable,
};
export default meta;
type Story = StoryObj<typeof OrderTable>;

export const Default: Story = {};

import type { Meta, StoryObj } from '@storybook/react-vite';
import PositionTable from './PositionTable';

const meta: Meta<typeof PositionTable> = {
  title: 'Components/PositionTable',
  component: PositionTable,
};
export default meta;
type Story = StoryObj<typeof PositionTable>;

export const Default: Story = {};

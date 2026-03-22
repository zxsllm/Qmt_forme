import type { Meta, StoryObj } from '@storybook/react-vite';
import AccountCard from './AccountCard';

const meta: Meta<typeof AccountCard> = {
  title: 'Components/AccountCard',
  component: AccountCard,
};
export default meta;
type Story = StoryObj<typeof AccountCard>;

export const Default: Story = {};

import type { Meta, StoryObj } from '@storybook/react-vite';
import Panel from './Panel';

const meta: Meta<typeof Panel> = {
  title: 'Components/Panel',
  component: Panel,
};
export default meta;
type Story = StoryObj<typeof Panel>;

export const Default: Story = {
  args: {
    title: '面板标题',
    children: <div className="text-t2 text-sm">面板内容区域</div>,
  },
};

export const Secondary: Story = {
  args: {
    title: '次级标题',
    secondary: true,
    children: <div className="text-t2 text-sm">次级面板</div>,
  },
};

export const WithExtra: Story = {
  args: {
    title: '带操作',
    extra: <button className="text-accent text-xs">操作</button>,
    children: <div className="text-t2 text-sm">带额外操作的面板</div>,
  },
};

export const NoPadding: Story = {
  args: {
    title: '无内距(表格)',
    noPadding: true,
    children: <div className="bg-bg-hover h-24" />,
  },
};

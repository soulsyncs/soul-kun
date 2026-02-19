/**
 * Tests for KPI Card component
 * Verifies rendering, formatting, trend indicators
 */

import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Activity } from 'lucide-react';
import { KpiCard } from './kpi-card';

describe('KpiCard', () => {
  it('renders title and value', () => {
    render(<KpiCard title="Conversations" value={1234} icon={Activity} />);
    expect(screen.getByText('Conversations')).toBeInTheDocument();
    expect(screen.getByText('1,234')).toBeInTheDocument();
  });

  it('formats currency values', () => {
    render(
      <KpiCard title="Cost" value={4250} icon={Activity} format="currency" />
    );
    expect(screen.getByText('¥4250')).toBeInTheDocument();
  });

  it('formats seconds values', () => {
    render(
      <KpiCard title="Time" value={3.7} icon={Activity} format="seconds" />
    );
    expect(screen.getByText('3.7s')).toBeInTheDocument();
  });

  it('formats ms values', () => {
    render(
      <KpiCard title="Latency" value={150} icon={Activity} format="ms" />
    );
    expect(screen.getByText('150ms')).toBeInTheDocument();
  });

  it('renders string values directly', () => {
    render(<KpiCard title="Rate" value="95.2%" icon={Activity} />);
    expect(screen.getByText('95.2%')).toBeInTheDocument();
  });

  it('shows positive trend with percentage', () => {
    render(
      <KpiCard title="Growth" value={100} icon={Activity} change={12.5} />
    );
    expect(screen.getByText('12.5%')).toBeInTheDocument();
    expect(screen.getByText('前期間比')).toBeInTheDocument();
  });

  it('shows negative trend with percentage', () => {
    render(
      <KpiCard title="Decline" value={100} icon={Activity} change={-5.3} />
    );
    expect(screen.getByText('5.3%')).toBeInTheDocument();
  });

  it('hides trend when change is undefined', () => {
    render(<KpiCard title="Static" value={100} icon={Activity} />);
    expect(screen.queryByText('前期間比')).not.toBeInTheDocument();
  });

  it('shows neutral badge when change is 0', () => {
    render(
      <KpiCard title="Flat" value={100} icon={Activity} change={0} />
    );
    expect(screen.getByText('0.0%')).toBeInTheDocument();
  });
});

/** Dashboard 加载态 —— 5 张卡 + 表格骨架 */
export default function DashboardLoading() {
  return (
    <div className="mx-auto flex max-w-[1400px] flex-col gap-6 p-6">
      <div className="h-16 animate-pulse rounded bg-surface-container-low" />
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {Array.from({ length: 5 }).map((_, i) => (
          <div
            key={i}
            className="h-28 animate-pulse rounded-lg border border-outline-variant bg-surface-container-lowest"
          />
        ))}
      </div>
      <div className="h-96 animate-pulse rounded-lg border border-outline-variant bg-surface-container-lowest" />
    </div>
  );
}

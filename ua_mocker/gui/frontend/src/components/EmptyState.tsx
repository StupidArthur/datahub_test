export function EmptyState({ icon, title, desc }: { icon: string; title: string; desc?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <div className="text-[40px] leading-none mb-3 text-muted-foreground/40">{icon}</div>
      <div className="text-[15px] font-semibold text-muted-foreground">{title}</div>
      {desc && <div className="text-[12.5px] text-muted-foreground/60 mt-1">{desc}</div>}
    </div>
  )
}

// F19.2 (#105): the single boldest element in the morning flow (PRD #102
// story 8). Renders the raw recommendation enum GO/MODIFY/MODALITY_SWAP/
// ABORT exactly as the backend sends it -- no frontend relabeling, the
// backend stays the source of truth for verdict text. This is the one and
// only place the reserved --color-accent token (index.css/#104) is used.
function VerdictStamp({ recommendation }: { recommendation: string }) {
  return (
    <div
      data-testid="verdict-stamp"
      className="rounded-md border-2 border-accent bg-surface-card px-6 py-8 text-center"
    >
      <p className="mb-1 font-mono text-xs font-medium tracking-widest text-text-muted uppercase">
        Recommendation
      </p>
      <p className="font-mono text-4xl font-bold tracking-tight text-accent uppercase sm:text-5xl">
        {recommendation}
      </p>
    </div>
  )
}

export default VerdictStamp

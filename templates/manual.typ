// Wiren Board Manual Template

// Parameters (set by the Python generator)
#let doc-title = ""
#let doc-date = ""
#let doc-cover-image = ""
#let doc-url = ""
#let doc-revid = ""

// Page setup
#set page(
  paper: "a4",
  margin: (top: 2.5cm, bottom: 2.5cm, left: 2cm, right: 2cm),
  header: context {
    if counter(page).get().first() > 2 [
      #set text(9pt, fill: gray)
      #h(1fr)
      #if doc-url != "" {
        link(doc-url, emph(doc-title))
      } else {
        emph(doc-title)
      }
    ]
  },
  footer: context {
    if counter(page).get().first() > 1 [
      #set text(9pt, fill: gray)
      #h(1fr)
      #counter(page).display("1 / 1", both: true)
    ]
  },
)

// Typography
#set text(
  font: "PT Sans",
  size: 10pt,
  lang: "ru",
)

#set par(
  justify: true,
  leading: 0.65em,
)

// Headings — sticky prevents orphaned headings at page bottom
#set heading(numbering: "1.1.1")
#show heading: set block(sticky: true)
#show heading.where(level: 1): set text(16pt, weight: "bold")
#show heading.where(level: 1): set block(above: 1.5em, below: 0.8em)
#show heading.where(level: 2): set text(13pt, weight: "bold")
#show heading.where(level: 2): set block(above: 1.2em, below: 0.6em)
#show heading.where(level: 3): set text(11pt, weight: "bold")
#show heading.where(level: 3): set block(above: 1em, below: 0.5em)

// Code blocks
#show raw.where(block: true): it => {
  block(
    width: 100%,
    fill: luma(245),
    stroke: luma(200),
    inset: 10pt,
    radius: 3pt,
    it,
  )
}

// Tables
#set table(
  stroke: 0.5pt + luma(150),
  inset: 6pt,
  align: left,
)

// Table figure captions: "Таблица N: ..." above the table
#show figure.where(kind: table): set figure(supplement: "Таблица")
#show figure.where(kind: table): set figure.caption(position: top)
#show figure.where(kind: table): set block(breakable: true)

// Figure images are centered via the figure itself; no global image show rule
// to avoid affecting inline images in tables and grids

// Helper: image constrained to max 50% page height for tall/portrait images
#let constrained-image(path, ..args) = layout(size => {
  let max-h = size.height * 50%
  let named = args.named()
  let w = named.at("width", default: 100%)
  let concrete-w = size.width * w
  let img-concrete = image(path, width: concrete-w)
  let natural = measure(img-concrete)
  if natural.height > max-h {
    let ratio = max-h / natural.height
    image(path, width: concrete-w * ratio, height: max-h)
  } else {
    image(path, width: concrete-w)
  }
})

// Helper: gallery image — constrained by a custom max height (% of page)
#let gallery-constrained-image(path, ..args) = layout(size => {
  let named = args.named()
  let w = named.at("width", default: 100%)
  let mh = named.at("max-height", default: 40%)
  let concrete-w = size.width * w
  let max-h = size.height * mh
  let img-concrete = image(path, width: concrete-w)
  let natural = measure(img-concrete)
  if natural.height > max-h {
    let ratio = max-h / natural.height
    image(path, width: concrete-w * ratio, height: max-h)
  } else {
    image(path, width: concrete-w)
  }
})

// Links
#show link: it => {
  text(fill: rgb("#0645AD"), it)
}

// Note/callout box function
#let note-box(title: "Примечание", color: rgb("#1a73e8"), body) = {
  block(
    width: 100%,
    inset: 10pt,
    radius: 3pt,
    stroke: (left: 3pt + color),
    fill: color.lighten(92%),
    [
      #text(weight: "bold", fill: color)[#title]
      #v(4pt)
      #body
    ],
  )
}

// Warning box
#let warning-box(body) = note-box(title: "Внимание", color: rgb("#e8a01a"), body)

// === Title page ===
#align(center)[
  #v(3cm)
  #if doc-cover-image != "" {
    image(doc-cover-image, width: 40%)
    v(1.5cm)
  } else {
    v(3cm)
  }
  #text(24pt, weight: "bold")[#doc-title]
  #v(1cm)
  #if doc-url != "" {
    link(doc-url, text(12pt, fill: gray)[#doc-url])
  } else {
    text(12pt, fill: gray)[wiki.wirenboard.com]
  }
  #v(0.5cm)
  #if doc-revid != "" {
    text(10pt, fill: gray)[Ревизия #doc-revid от #doc-date]
  } else {
    text(11pt, fill: gray)[#doc-date]
  }
]

#pagebreak()

// Table of contents
#outline(title: "Содержание", indent: 1.5em, depth: 3)
#pagebreak()

/* ── Building / crane canvas animation ─────────────── */
(function () {
  const canvas = document.getElementById('scene');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let W, H, tick = 0;

  const BUILDINGS = [
    { x: 28,  w: 46, h: 115, fl: 5 },
    { x: 82,  w: 36, h: 155, fl: 7 },
    { x: 126, w: 54, h:  82, fl: 3 },
    { x: 188, w: 40, h: 172, fl: 8 },
    { x: 237, w: 34, h:  96, fl: 4 },
    { x: 279, w: 48, h:  62, fl: 2 },
    { x: 678, w: 38, h: 133, fl: 6 },
    { x: 724, w: 46, h:  92, fl: 4 },
    { x: 778, w: 42, h: 163, fl: 7 },
    { x: 828, w: 36, h:  76, fl: 3 },
    { x: 872, w: 50, h: 122, fl: 5 },
    { x: 930, w: 38, h: 102, fl: 4 },
  ];

  const CRANES = [
    { bx: 428, by: 118, arm: 200, offset: 90 },
    { bx: 558, by:  88, arm: 162, offset: 70 },
  ];

  function resize() {
    W = canvas.width  = canvas.offsetWidth;
    H = canvas.height = canvas.offsetHeight;
  }
  window.addEventListener('resize', resize);
  resize();

  function draw() {
    const sx = W / 960, sy = H / 480;
    ctx.clearRect(0, 0, W, H);

    /* Sky */
    const sky = ctx.createLinearGradient(0, 0, 0, H);
    sky.addColorStop(0,   '#050B18');
    sky.addColorStop(0.5, '#0C1828');
    sky.addColorStop(1,   '#162438');
    ctx.fillStyle = sky;
    ctx.fillRect(0, 0, W, H);

    /* Stars */
    for (let i = 0; i < 50; i++) {
      const x = ((i * 41 + 13) % 100) / 100 * W;
      const y = ((i * 29 +  7) %  50) / 100 * H;
      const a = 0.1 + 0.25 * Math.sin(tick * 0.04 + i);
      ctx.beginPath();
      ctx.arc(x, y, i % 4 === 0 ? 1.3 : 0.7, 0, Math.PI * 2);
      ctx.fillStyle = `rgba(255,255,255,${a})`;
      ctx.fill();
    }

    /* Moon */
    ctx.beginPath();
    ctx.arc(W * 0.88, H * 0.1, H * 0.04, 0, Math.PI * 2);
    ctx.shadowBlur = 28; ctx.shadowColor = '#F4EEE066';
    ctx.fillStyle = '#F4EEE0';
    ctx.fill();
    ctx.shadowBlur = 0;

    /* Ground */
    ctx.fillStyle = '#080E1C';
    ctx.fillRect(0, H * 0.9, W, H * 0.1);
    ctx.strokeStyle = '#1A3050'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, H * 0.9); ctx.lineTo(W, H * 0.9); ctx.stroke();

    /* Buildings */
    BUILDINGS.forEach((b, i) => {
      const prog = Math.min(1, (Math.sin((tick * 0.35 + i * 19) * Math.PI / 180) + 1) / 2);
      const height = Math.max(16, b.h * (0.25 + 0.75 * prog));
      const bx = b.x * sx, bw = b.w * sx;
      const by = H * 0.9 - height * sy, bh = height * sy;

      ctx.fillStyle   = '#0E1A2E';
      ctx.strokeStyle = '#1A3050';
      ctx.lineWidth = 0.6;
      ctx.fillRect(bx, by, bw, bh);
      ctx.strokeRect(bx, by, bw, bh);

      const floorH = bh / (b.fl || 4);
      for (let fi = 0; fi < (b.fl || 4); fi++) {
        const cols = Math.floor(b.w / 14);
        for (let wi = 0; wi < cols; wi++) {
          const wx = bx + 5 * sx + wi * 14 * sx;
          const wy = by + fi * floorH + 5 * sy;
          if (wx + 7 * sx > bx + bw - 4 * sx) continue;
          const lit = ((i * 7 + fi * 3 + wi * 5 + Math.floor(tick / 22)) % 11) < 7;
          ctx.fillStyle = lit ? 'rgba(246,202,76,.88)' : 'rgba(8,18,36,.6)';
          ctx.fillRect(wx, wy, 7 * sx, 8 * sy);
        }
      }

      /* Antenna */
      ctx.fillStyle = '#AD8A4D';
      ctx.fillRect(bx + bw / 2 - 2 * sx, by - 9 * sy, 3 * sx, 9 * sy);
      ctx.beginPath();
      ctx.arc(bx + bw / 2, by - 11 * sy, 3 * sx, 0, Math.PI * 2);
      ctx.fillStyle = Math.floor(tick / 12) % 2 === 0 ? '#FF3333' : 'rgba(255,0,0,.2)';
      ctx.fill();
    });

    /* Cranes */
    CRANES.forEach((c, ci) => {
      const angle = Math.sin(tick * 0.05 + ci * 2) * 6 * Math.PI / 180;
      const px = (c.bx + 5) * sx, py = (c.by + 10) * sy;

      ctx.save();
      ctx.translate(px, py);
      ctx.rotate(angle);
      ctx.translate(-px, -py);

      ctx.fillStyle   = '#AD8A4D';
      ctx.strokeStyle = '#AD8A4D';
      /* Mast */
      ctx.fillRect(c.bx * sx, c.by * sy, 9 * sx, (200 - c.by) * sy);
      /* Jib */
      ctx.fillRect((c.bx - c.offset) * sx, c.by * sy + 9 * sy, c.arm * sx, 5 * sy);

      /* Hoist rope */
      const hoistY = (75 + 28 * Math.sin(tick * 0.06 + ci)) * sy;
      ctx.beginPath();
      ctx.moveTo((c.bx + c.arm - c.offset - 9) * sx, (c.by + 40) * sy);
      ctx.lineTo((c.bx + c.arm - c.offset - 9) * sx, hoistY + 58 * sy);
      ctx.strokeStyle = 'rgba(244,238,224,.45)';
      ctx.lineWidth = 1;
      ctx.stroke();

      /* Load */
      ctx.fillStyle   = '#224478';
      ctx.strokeStyle = '#AD8A4D';
      ctx.lineWidth = 0.8;
      ctx.fillRect((c.bx + c.arm - c.offset - 18) * sx, hoistY + 58 * sy, 16 * sx, 11 * sy);
      ctx.strokeRect((c.bx + c.arm - c.offset - 18) * sx, hoistY + 58 * sy, 16 * sx, 11 * sy);

      ctx.restore();
    });

    tick++;
    requestAnimationFrame(draw);
  }

  draw();
})();

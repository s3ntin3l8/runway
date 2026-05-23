// Run with: node tests/frontend/test_spark_helpers.js

function _niceMax(v) {
    if (v <= 0) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(v)));
    const norm = v / mag;
    const nice = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10;
    return nice * mag;
}

function _fmtTick(v) {
    if (v >= 1e6) return (v / 1e6).toFixed(v % 1e6 === 0 ? 0 : 1) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(v % 1e3 === 0 ? 0 : 1) + 'K';
    return Math.round(v).toString();
}

let passed = 0, failed = 0;
function assert(desc, got, want) {
    if (got === want) { console.log(`  ✓ ${desc}`); passed++; }
    else { console.error(`  ✗ ${desc}: got ${got}, want ${want}`); failed++; }
}

// _niceMax
assert('niceMax(1)    = 1',       _niceMax(1),       1);
assert('niceMax(87)   = 100',     _niceMax(87),      100);
assert('niceMax(1500) = 2000',    _niceMax(1500),    2000);
assert('niceMax(2100) = 2500',    _niceMax(2100),    2500);
assert('niceMax(3500) = 5000',    _niceMax(3500),    5000);
assert('niceMax(8000) = 10000',   _niceMax(8000),    10000);
assert('niceMax(11000)= 20000',   _niceMax(11000),   20000);
assert('niceMax(50000)= 50000',   _niceMax(50000),   50000);
assert('niceMax(100000)=100000',  _niceMax(100000),  100000);

// _fmtTick
assert('fmtTick(500)   = "500"',  _fmtTick(500),    '500');
assert('fmtTick(1000)  = "1K"',   _fmtTick(1000),   '1K');
assert('fmtTick(2500)  = "2.5K"', _fmtTick(2500),   '2.5K');
assert('fmtTick(50000) = "50K"',  _fmtTick(50000),  '50K');
assert('fmtTick(1.5e6) = "1.5M"',_fmtTick(1.5e6),  '1.5M');
assert('fmtTick(2e6)   = "2M"',   _fmtTick(2e6),    '2M');

console.log(`\n${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);

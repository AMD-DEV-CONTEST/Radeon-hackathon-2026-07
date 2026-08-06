
const fs = require('fs');
const results = JSON.parse(fs.readFileSync('e:/VisioLab/Kido-Dev-Frontend/Kido-Dev-Frontend/kido-dev-frontend/scratch/curriculum_results_utf8.json', 'utf8').replace(/^\uFEFF/, ''));

let sql = '-- Update curriculum intelligence\n';

for (const r of results) {
    // Escape single quotes for SQL
    const xml = r.xml.replace(/'/g, "''");
    const stepsJson = JSON.stringify(r.steps).replace(/'/g, "''");
    const solveMsg = (r.solve_message || `I have calculated the perfect solution for ${r.id}!`).replace(/'/g, "''");
    const solveTip = (r.solve_tip || 'Follow the blocks to see the result.').replace(/'/g, "''");

    // Update tutor_solutions
    sql += `INSERT INTO tutor_solutions (lesson_id, xml, message, tip)
VALUES ('${r.id}', '${xml}', '${solveMsg}', '${solveTip}')
ON CONFLICT (lesson_id) DO UPDATE SET xml = EXCLUDED.xml, message = EXCLUDED.message, tip = EXCLUDED.tip;\n\n`;

    // Update lessons steps
    sql += `UPDATE lessons SET steps = '${stepsJson}' WHERE id = '${r.id}';\n\n`;

    // Clear and refill tutorial_steps
    sql += `DELETE FROM tutorial_steps WHERE lesson_id = '${r.id}';\n`;
    r.steps.forEach((s, idx) => {
        const msg = s.message.replace(/'/g, "''");
        const checkVal = s.check_xml_contains.replace(/'/g, "''");
        sql += `INSERT INTO tutorial_steps (lesson_id, step_index, message, check_xml_contains)
VALUES ('${r.id}', ${idx}, '${msg}', '${checkVal}');\n`;
    });
    sql += '\n';
}

fs.writeFileSync('e:/VisioLab/Kido-Dev-Frontend/Kido-Dev-Frontend/kido-dev-frontend/scratch/update_db.sql', sql);
console.log('SQL generated!');

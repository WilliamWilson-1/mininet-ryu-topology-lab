"""Optional Node parity checks for all 380 ordered demo host pairs on both pages."""
from collections import deque
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from paths import dfs_paths
from topologies import topology_catalog


@unittest.skipUnless(shutil.which('node'), 'Node is optional; needed for browser DFS checks')
class DemoPathTests(unittest.TestCase):
    def test_all_pairs_match_controller_and_bfs(self):
        root = Path(__file__).resolve().parent.parent
        script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const html=fs.readFileSync(process.argv[1],'utf8');
const edges=JSON.parse(fs.readFileSync(process.argv[2],'utf8'))[process.argv[3]].edges;
const fn=html.slice(html.indexOf('async function calculateDemoPaths('),html.indexOf('let demoCatalog,demoSwitching=false;'));
assert(fn.startsWith('async function calculateDemoPaths('));
const scope=vm.createContext({performance,setTimeout,DEMO_EDGES:edges});vm.runInContext(fn,scope);
(async()=>{
 const results=[];
 for(let a=1;a<=20;a++)for(let b=1;b<=20;b++)if(a!==b){
  const r=await scope.calculateDemoPaths('h'+a,'h'+b);
  for(const p of [r.shortest,r.longest]){
   assert.equal(p[0],a);assert.equal(p.at(-1),b);assert.equal(new Set(p).size,p.length);
   for(let i=1;i<p.length;i++)assert(edges.some(([x,y])=>(x===p[i-1]&&y===p[i])||(y===p[i-1]&&x===p[i])));
  }results.push(r);
 }
 for(const args of [['h1','h1'],['h0','h20'],['h1','h21'],['h1','h20',[]]])await assert.rejects(scope.calculateDemoPaths(...args));
 console.log(JSON.stringify(results));
})().catch(e=>{console.error(e);process.exitCode=1});
'''
        for name, config in topology_catalog().items():
            edges = config['edges']
            graph = {i: set() for i in range(1, 21)}
            for a, b in edges:
                graph[a].add(b)
                graph[b].add(a)
            for page in ('docs/index.html', 'lab/static/index.html'):
                with self.subTest(topology=name, page=page):
                    process = subprocess.run(
                        ['node', '-e', script, str(root / page), str(root / 'docs/topologies.json'), name],
                        capture_output=True, text=True, check=True, timeout=90,
                    )
                    results = json.loads(process.stdout)
                    self.assertEqual(len(results), 380)
                    for actual in results:
                        a, b = int(actual['src'][1:]), int(actual['dst'][1:])
                        expected = dfs_paths(graph, a, b)
                        for key in ('shortest', 'longest', 'shortest_hops', 'longest_hops',
                                    'simple_path_count', 'dfs_visits', 'exact'):
                            self.assertEqual(actual[key], expected[key], (page, a, b, key))
                        distance, queue = {a: 0}, deque([a])
                        while queue:
                            node = queue.popleft()
                            for neighbor in graph[node]:
                                if neighbor not in distance:
                                    distance[neighbor] = distance[node] + 1
                                    queue.append(neighbor)
                        self.assertEqual(actual['shortest_hops'], distance[b])


if __name__ == '__main__':
    unittest.main()

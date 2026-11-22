const EN = {
  preparing: "Preparing model…",
  fit: "Fit",
  fitLabel: "Fit the model to the view",
  reset: "Reset",
  resetLabel: "Reset the camera",
  top: "Top",
  front: "Front",
  iso: "Iso",
  viewLabel: (name) => `${name} view`,
  edges: "Edges",
  edgesLabel: "Show feature edges",
  edgesSkipped: "Edges are not drawn above 600,000 triangles",
  viewport:
    "3D model. Drag to rotate, scroll or pinch to zoom, right-drag to pan. Arrow keys pan; Shift and an arrow key rotate.",
  dimensions: (x, y, z) => `Bounding box ${x} × ${y} × ${z} mm (from the mesh)`,
  failed: (report) =>
    `This build failed a check, so this is not the part that was asked for. See ${report} for what failed.`,
  lost: "Display lost",
  reload: "Reload",
  download: "Download original",
  reasons: {
    "too-many-triangles":
      "This model has more than 1,000,000 triangles, over the preview limit.",
    "too-many-vertices":
      "This model has more than 1,000,000 vertices, over the preview limit.",
    "too-many-parts":
      "This model has more than 20,000 parts or nodes, over the preview limit.",
    "external-buffer":
      "This GLB keeps its data in other files, which the preview does not fetch.",
    "unsupported-extension":
      "This GLB needs a glTF extension the preview does not read, such as mesh compression.",
    "unsupported-primitive":
      "This model uses points, lines or an encoding the preview does not draw.",
    "node-cycle": "This GLB's node tree is not a tree: a node is reached twice.",
    "too-deep": "This GLB's node tree is deeper than 64 levels.",
    "non-finite": "This model contains coordinates that are not numbers.",
    truncated: "This STL file is cut short or damaged.",
    empty: "This model contains no triangles.",
    timeout: "Preparing this model took longer than 15 seconds.",
    "worker-failed": "This browser could not prepare the model.",
    "invalid-file": "This file is damaged, or is not a binary glTF (GLB) or STL model.",
  },
};

const ZH = {
  preparing: "正在准备模型…",
  fit: "适应",
  fitLabel: "让模型适应视图",
  reset: "重置",
  resetLabel: "重置相机",
  top: "俯视",
  front: "前视",
  iso: "轴测",
  viewLabel: (name) => `${name}图`,
  edges: "棱线",
  edgesLabel: "显示特征棱线",
  edgesSkipped: "超过 600,000 个三角形时不绘制棱线",
  viewport:
    "三维模型。拖动旋转，滚轮或双指缩放，右键拖动平移。方向键平移，Shift 加方向键旋转。",
  dimensions: (x, y, z) => `包围盒 ${x} × ${y} × ${z} mm（按网格计算）`,
  failed: (report) => `此构建未通过检查，显示的不是所要求的零件。失败原因见 ${report}。`,
  lost: "显示已丢失",
  reload: "重新加载",
  download: "下载原始文件",
  reasons: {
    "too-many-triangles": "此模型超过 1,000,000 个三角形，超出预览上限。",
    "too-many-vertices": "此模型超过 1,000,000 个顶点，超出预览上限。",
    "too-many-parts": "此模型超过 20,000 个部件或节点，超出预览上限。",
    "external-buffer": "此 GLB 的数据保存在其他文件中，预览不会获取外部文件。",
    "unsupported-extension": "此 GLB 需要预览不支持的 glTF 扩展，例如网格压缩。",
    "unsupported-primitive": "此模型使用点、线或预览无法绘制的编码。",
    "node-cycle": "此 GLB 的节点不是树结构：有节点被引用了两次。",
    "too-deep": "此 GLB 的节点层级超过 64 层。",
    "non-finite": "此模型包含无效的坐标数值。",
    truncated: "此 STL 文件不完整或已损坏。",
    empty: "此模型不包含三角形。",
    timeout: "准备此模型超过 15 秒。",
    "worker-failed": "此浏览器无法准备该模型。",
    "invalid-file": "此文件已损坏，或不是二进制 glTF（GLB）或 STL 模型。",
  },
};

export function strings(locale) {
  return String(locale).toLowerCase().startsWith("zh") ? ZH : EN;
}

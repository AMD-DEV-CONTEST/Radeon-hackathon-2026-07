let counter = 0;
module.exports = {
  nanoid(size = 21) {
    return `${++counter}`.padStart(size, "0");
  },
};
